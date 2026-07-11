"""
src/agents/rl_dreamer.py — DreamerV3-스타일 월드모델 RL 트레이너

일봉+분봉 combined 데이터셋(일중 특징 관측)을 소비하는 model-based RL.
RSSM(순환 잠재 동역학) 월드모델을 학습하고, 그 모델 안에서 '상상(imagination)'
롤아웃으로 액터-크리틱을 학습한다 — 부족한 실데이터를 잠재 시뮬레이션으로 증폭.

DreamerV3-스타일(컴팩트) 구현 — 핵심 구조를 충실히 따르되 CPU/소규모 운영을 위해
간소화한 부분을 명시한다:
  - 잠재 stoch: 가우시안(원 논문은 categorical). 벡터 관측엔 가우시안이 단순·안정.
  - symlog 관측 변환, KL balancing + free bits 는 채택.
  - 이산 행동 액터는 REINFORCE(+엔트로피)로 상상 λ-리턴 학습.

오프라인(금융) 특성상 환경은 과거 시퀀스를 고정 리플레이하는 TradingEnv 를 쓴다.
공통 RLPolicy 인터페이스(rl_policy_interface)를 구현한 DreamerRLPolicy 로 추론한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from src.agents.rl_environment import (
    NUM_ACTIONS,
    TradingEnv,
    TradingEnvConfig,
    action_to_str,
    env_config_from_dataset,
)
from src.agents.rl_trading import (
    RLEvaluationMetrics,
    RLPolicyArtifact,
    RLSplitMetadata,
)
from src.utils.logging import get_logger

# DreamerV3 모델 체크포인트 저장 디렉토리
_DREAMER_MODEL_DIR = "artifacts/rl/models/dreamer"

logger = get_logger(__name__)


def symlog(x: torch.Tensor) -> torch.Tensor:
    return torch.sign(x) * torch.log1p(torch.abs(x))


def symexp(x: torch.Tensor) -> torch.Tensor:
    return torch.sign(x) * torch.expm1(torch.abs(x))


@dataclass
class DreamerConfig:
    """DreamerV3 트레이너 하이퍼파라미터 (CPU·소규모 기본값)."""

    deter_dim: int = 32
    stoch_dim: int = 16
    hidden_dim: int = 64
    horizon: int = 5            # 상상 롤아웃 길이
    seq_len: int = 32           # 월드모델 학습 시퀀스 길이
    batch_size: int = 16
    train_iters: int = 60       # 월드모델/AC 업데이트 횟수
    collect_episodes: int = 6   # 리플레이 수집 에피소드 수
    lr: float = 6e-4
    gamma: float = 0.99
    lam: float = 0.95           # λ-리턴
    kl_scale: float = 1.0
    kl_free: float = 1.0        # free bits (nats)
    entropy_scale: float = 3e-3
    explore_eps: float = 0.3    # 수집 시 탐색률
    lookback: int = 20
    grad_clip: float = 100.0
    seed: int = 0


# ── 신경망 ─────────────────────────────────────────────────────────────────


def _mlp(in_dim: int, hidden: int, out_dim: int, layers: int = 2) -> nn.Sequential:
    mods: list[nn.Module] = [nn.Linear(in_dim, hidden), nn.SiLU()]
    for _ in range(layers - 1):
        mods += [nn.Linear(hidden, hidden), nn.SiLU()]
    mods += [nn.Linear(hidden, out_dim)]
    return nn.Sequential(*mods)


class RSSM(nn.Module):
    """Recurrent State-Space Model — 결정론적 GRU + 가우시안 stoch 잠재."""

    def __init__(self, obs_dim: int, action_dim: int, cfg: DreamerConfig) -> None:
        super().__init__()
        self.deter = cfg.deter_dim
        self.stoch = cfg.stoch_dim
        self.action_dim = action_dim
        self.embed = _mlp(obs_dim, cfg.hidden_dim, cfg.hidden_dim)
        self.gru = nn.GRUCell(cfg.stoch_dim + action_dim, cfg.deter_dim)
        self.prior_net = _mlp(cfg.deter_dim, cfg.hidden_dim, 2 * cfg.stoch_dim)
        self.post_net = _mlp(cfg.deter_dim + cfg.hidden_dim, cfg.hidden_dim, 2 * cfg.stoch_dim)
        self.feat_dim = cfg.deter_dim + cfg.stoch_dim

    def initial(self, batch: int, device: torch.device) -> tuple[torch.Tensor, torch.Tensor]:
        return (
            torch.zeros(batch, self.deter, device=device),
            torch.zeros(batch, self.stoch, device=device),
        )

    @staticmethod
    def _dist(params: torch.Tensor) -> torch.distributions.Normal:
        mean, std = torch.chunk(params, 2, dim=-1)
        std = F.softplus(std) + 0.1
        return torch.distributions.Normal(mean, std)

    def obs_step(self, prev_stoch, prev_action, prev_deter, obs_embed):
        x = torch.cat([prev_stoch, prev_action], dim=-1)
        deter = self.gru(x, prev_deter)
        prior = self._dist(self.prior_net(deter))
        post = self._dist(self.post_net(torch.cat([deter, obs_embed], dim=-1)))
        stoch = post.rsample()
        return deter, stoch, prior, post

    def img_step(self, prev_stoch, prev_action, prev_deter):
        x = torch.cat([prev_stoch, prev_action], dim=-1)
        deter = self.gru(x, prev_deter)
        prior = self._dist(self.prior_net(deter))
        stoch = prior.rsample()
        return deter, stoch, prior

    @staticmethod
    def feat(deter, stoch):
        return torch.cat([deter, stoch], dim=-1)


class WorldModel(nn.Module):
    def __init__(self, obs_dim: int, action_dim: int, cfg: DreamerConfig) -> None:
        super().__init__()
        self.rssm = RSSM(obs_dim, action_dim, cfg)
        feat = self.rssm.feat_dim
        self.decoder = _mlp(feat, cfg.hidden_dim, obs_dim)
        self.reward = _mlp(feat, cfg.hidden_dim, 1)
        self.cont = _mlp(feat, cfg.hidden_dim, 1)


class ActorCritic(nn.Module):
    def __init__(self, feat_dim: int, action_dim: int, cfg: DreamerConfig) -> None:
        super().__init__()
        self.actor = _mlp(feat_dim, cfg.hidden_dim, action_dim)
        self.critic = _mlp(feat_dim, cfg.hidden_dim, 1)


# ── 트레이너 ───────────────────────────────────────────────────────────────


class DreamerV3Trainer:
    """DreamerV3-스타일 월드모델 트레이너.

    train(dataset) → 월드모델 학습 + 상상 액터크리틱 학습 + 홀드아웃 평가.
    학습된 가중치는 state_dict 로 보관(아티팩트 저장은 정책 스토어 담당).
    """

    algorithm = "dreamer_v3"

    def __init__(self, cfg: DreamerConfig | None = None, **overrides: Any) -> None:
        self.cfg = cfg or DreamerConfig(**overrides)
        self.device = torch.device("cpu")
        self.obs_dim: int | None = None
        self.world: WorldModel | None = None
        self.ac: ActorCritic | None = None

    # -- public --------------------------------------------------------------

    def build_env(self, dataset: Any, *, closes=None, features=None) -> TradingEnv:
        if closes is not None:
            cfg = TradingEnvConfig(
                closes=list(closes),
                intraday_features=features,
                lookback=self.cfg.lookback,
            )
        else:
            cfg = env_config_from_dataset(dataset, lookback=self.cfg.lookback)
        return TradingEnv(cfg)

    # -- trainer 계약 (RLContinuousImprover 호환) ---------------------------

    def train_with_metadata(
        self,
        dataset: Any,
        *,
        train_ratio: float = 0.7,
        on_progress: Any = None,
    ) -> tuple[RLPolicyArtifact, RLSplitMetadata]:
        """SB3/tabular 트레이너와 동일한 계약: (artifact, split_metadata) 반환."""
        if len(dataset.closes) <= self.cfg.lookback + 10:
            raise ValueError(
                f"RL 학습 길이가 너무 짧습니다: ticker={dataset.ticker}, "
                f"len={len(dataset.closes)}"
            )
        core = self._train_core(dataset, train_ratio)
        if on_progress is not None:
            on_progress(80)

        policy_id = (
            f"rl_{dataset.ticker}_"
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        )
        model_path = self._save_model(core, policy_id)
        ev = core["evaluation"]
        artifact = RLPolicyArtifact(
            policy_id=policy_id,
            ticker=dataset.ticker,
            created_at=datetime.now(timezone.utc).isoformat(),
            algorithm=self.algorithm,
            state_version="dreamer_v3",
            lookback=self.cfg.lookback,
            episodes=self.cfg.train_iters,
            learning_rate=self.cfg.lr,
            discount_factor=self.cfg.gamma,
            epsilon=self.cfg.explore_eps,
            trade_penalty_bps=2,
            evaluation=RLEvaluationMetrics(**ev),
            q_table=None,
            model_path=model_path,
        )
        split_meta = self._split_metadata(dataset, train_ratio)
        if on_progress is not None:
            on_progress(100)
        return artifact, split_meta

    def train(self, dataset: Any, train_ratio: float = 0.7, on_progress: Any = None) -> RLPolicyArtifact:
        return self.train_with_metadata(
            dataset, train_ratio=train_ratio, on_progress=on_progress
        )[0]

    def evaluate(
        self,
        model_path_or_prices: Any,
        closes_or_none: list[float] | None = None,
    ) -> RLEvaluationMetrics:
        """학습된 모델을 가격 시퀀스로 평가. 두 호출 패턴 지원(SB3 호환).

        - evaluate(model_path, closes)  — SB3 스타일
        - evaluate(closes, model_path)  — walk-forward 어댑터 스타일
        """
        if isinstance(model_path_or_prices, str):
            model_path, closes = model_path_or_prices, closes_or_none
        else:
            closes, model_path = model_path_or_prices, closes_or_none
        ckpt = torch.load(model_path, map_location="cpu", weights_only=False)
        self.load_state(ckpt["state_dict"], int(ckpt["obs_dim"]))
        # walk-forward 는 raw closes(특징 없음) 전달 → 일봉 전용 평가
        lookback = min(self.cfg.lookback, max(2, len(closes) - 2))
        env = TradingEnv(
            TradingEnvConfig(closes=[float(c) for c in closes], lookback=lookback)
        )
        obs, _ = env.reset()
        terminated = False
        steps = 0
        while not terminated and steps < len(env.closes):
            obs, _r, terminated, _t, _i = env.step(self._greedy_action(obs))
            steps += 1
        summ = env.get_episode_summary()
        approved = summ["excess_return_pct"] > 0.0 and summ["max_drawdown_pct"] > -40.0
        return RLEvaluationMetrics(
            total_return_pct=summ["total_return_pct"],
            baseline_return_pct=summ["baseline_return_pct"],
            excess_return_pct=summ["excess_return_pct"],
            max_drawdown_pct=summ["max_drawdown_pct"],
            trades=summ["total_trades"],
            win_rate=summ["win_rate"],
            holdout_steps=summ["steps"],
            approved=bool(approved),
        )

    def _save_model(self, core: dict, policy_id: str) -> str:
        os.makedirs(_DREAMER_MODEL_DIR, exist_ok=True)
        path = os.path.join(_DREAMER_MODEL_DIR, f"{policy_id}.pt")
        save_dreamer_checkpoint(path, core)
        return path

    def _split_metadata(self, dataset: Any, train_ratio: float) -> RLSplitMetadata:
        n = len(dataset.closes)
        split_idx = max(self.cfg.lookback + 5, int(n * train_ratio))
        split_idx = min(split_idx, n - 3)
        ts = list(getattr(dataset, "timestamps", None) or [str(i) for i in range(n)])
        return RLSplitMetadata(
            train_ratio=train_ratio,
            train_size=split_idx,
            test_size=n - split_idx,
            train_start=str(ts[0]),
            train_end=str(ts[min(split_idx - 1, n - 1)]),
            test_start=str(ts[min(split_idx, n - 1)]),
            test_end=str(ts[-1]),
        )

    # -- 내부 학습 코어 ------------------------------------------------------

    def _train_core(self, dataset: Any, train_ratio: float = 0.7) -> dict:
        """월드모델+AC 학습 후 학습 결과/평가 dict 반환.

        반환: {state_dict, obs_dim, evaluation(dict), config}
        """
        torch.manual_seed(self.cfg.seed)
        np.random.seed(self.cfg.seed)

        closes = [float(c) for c in dataset.closes]
        feats = getattr(dataset, "features", None)
        split = max(self.cfg.lookback + 5, int(len(closes) * train_ratio))
        split = min(split, len(closes) - 3)

        train_closes = closes[:split]
        train_feats = [list(f) for f in feats[:split]] if feats else None
        env = self.build_env(dataset, closes=train_closes, features=train_feats)

        self.obs_dim = int(env.observation_space.shape[0]) if hasattr(env, "observation_space") else len(env.reset()[0])
        self.world = WorldModel(self.obs_dim, NUM_ACTIONS, self.cfg).to(self.device)
        self.ac = ActorCritic(self.world.rssm.feat_dim, NUM_ACTIONS, self.cfg).to(self.device)

        wm_opt = torch.optim.Adam(self.world.parameters(), lr=self.cfg.lr)
        ac_opt = torch.optim.Adam(self.ac.parameters(), lr=self.cfg.lr)

        # 1) 오프라인 리플레이 수집 (현재 액터 + 탐색)
        buffer = self._collect(env)

        # 2) 학습 루프
        for it in range(self.cfg.train_iters):
            batch = self._sample_batch(buffer)
            post_feats = self._train_world_model(batch, wm_opt)
            self._train_actor_critic(post_feats, ac_opt)

        # 3) 홀드아웃 평가
        evaluation = self._evaluate(dataset, closes, feats, split)

        state_dict = {
            "world": self.world.state_dict(),
            "ac": self.ac.state_dict(),
        }
        return {
            "state_dict": state_dict,
            "obs_dim": self.obs_dim,
            "evaluation": evaluation,
            "config": self.cfg.__dict__,
        }

    # -- collection ----------------------------------------------------------

    def _collect(self, env: TradingEnv) -> list[dict]:
        """env 를 여러 에피소드 리플레이하며 (obs, action, reward, cont) 시퀀스 수집."""
        episodes: list[dict] = []
        for _ in range(self.cfg.collect_episodes):
            obs, _ = env.reset()
            obs_seq, act_seq, rew_seq, cont_seq = [], [], [], []
            terminated = False
            steps = 0
            while not terminated and steps < len(env.closes):
                action = self._behavior_action(obs)
                next_obs, reward, terminated, _trunc, _info = env.step(action)
                obs_seq.append(obs)
                act_seq.append(action)
                rew_seq.append(reward)
                cont_seq.append(0.0 if terminated else 1.0)
                obs = next_obs
                steps += 1
            if len(obs_seq) >= 4:
                episodes.append(
                    {
                        "obs": np.asarray(obs_seq, dtype=np.float32),
                        "action": np.asarray(act_seq, dtype=np.int64),
                        "reward": np.asarray(rew_seq, dtype=np.float32),
                        "cont": np.asarray(cont_seq, dtype=np.float32),
                    }
                )
        if not episodes:
            raise ValueError("DreamerV3: 리플레이 수집 실패 (에피소드 없음)")
        return episodes

    def _behavior_action(self, obs: np.ndarray) -> int:
        if self.ac is None or np.random.rand() < self.cfg.explore_eps:
            return int(np.random.randint(NUM_ACTIONS))
        with torch.no_grad():
            # 단일 관측 기반 근사 행동 (수집용 — 잠재 워밍업 생략)
            t = torch.as_tensor(obs, dtype=torch.float32, device=self.device).unsqueeze(0)
            embed = self.world.rssm.embed(symlog(t))
            deter, stoch = self.world.rssm.initial(1, self.device)
            deter, stoch, _, _ = self.world.rssm.obs_step(
                stoch, self._onehot(torch.zeros(1, dtype=torch.long)), deter, embed
            )
            logits = self.ac.actor(self.world.rssm.feat(deter, stoch))
            return int(torch.argmax(logits, dim=-1).item())

    # -- world model ---------------------------------------------------------

    def _sample_batch(self, buffer: list[dict]) -> dict:
        L = self.cfg.seq_len
        obs_b, act_b, rew_b, cont_b = [], [], [], []
        for _ in range(self.cfg.batch_size):
            ep = buffer[np.random.randint(len(buffer))]
            n = len(ep["obs"])
            if n <= L:
                start = 0
                end = n
            else:
                start = np.random.randint(0, n - L)
                end = start + L
            sl = slice(start, end)
            obs_b.append(self._pad(ep["obs"][sl], L))
            act_b.append(self._pad(ep["action"][sl], L, fill=0))
            rew_b.append(self._pad(ep["reward"][sl], L))
            cont_b.append(self._pad(ep["cont"][sl], L, fill=1.0))
        return {
            "obs": torch.as_tensor(np.stack(obs_b), dtype=torch.float32, device=self.device),
            "action": torch.as_tensor(np.stack(act_b), dtype=torch.long, device=self.device),
            "reward": torch.as_tensor(np.stack(rew_b), dtype=torch.float32, device=self.device),
            "cont": torch.as_tensor(np.stack(cont_b), dtype=torch.float32, device=self.device),
        }

    @staticmethod
    def _pad(arr: np.ndarray, length: int, fill: float = 0.0) -> np.ndarray:
        if len(arr) >= length:
            return np.asarray(arr[:length])
        pad_shape = (length - len(arr),) + arr.shape[1:]
        return np.concatenate([arr, np.full(pad_shape, fill, dtype=arr.dtype)], axis=0)

    def _onehot(self, idx: torch.Tensor) -> torch.Tensor:
        return F.one_hot(idx, NUM_ACTIONS).float().to(self.device)

    def _train_world_model(self, batch: dict, opt: torch.optim.Optimizer) -> torch.Tensor:
        B, T, _ = batch["obs"].shape
        deter, stoch = self.world.rssm.initial(B, self.device)
        embeds = self.world.rssm.embed(symlog(batch["obs"]))  # (B,T,H)
        actions = self._onehot(batch["action"])  # (B,T,A)

        feats, recon_loss, rew_loss, cont_loss, kl_loss = [], 0.0, 0.0, 0.0, 0.0
        prev_action = torch.zeros(B, NUM_ACTIONS, device=self.device)
        for t in range(T):
            deter, stoch, prior, post = self.world.rssm.obs_step(
                stoch, prev_action, deter, embeds[:, t]
            )
            feat = self.world.rssm.feat(deter, stoch)
            feats.append(feat)
            recon = self.world.decoder(feat)
            recon_loss = recon_loss + F.mse_loss(recon, symlog(batch["obs"][:, t]))
            rew_pred = self.world.reward(feat).squeeze(-1)
            rew_loss = rew_loss + F.mse_loss(rew_pred, symlog(batch["reward"][:, t]))
            cont_pred = self.world.cont(feat).squeeze(-1)
            cont_loss = cont_loss + F.binary_cross_entropy_with_logits(cont_pred, batch["cont"][:, t])
            # KL balancing + free bits
            kl = torch.distributions.kl_divergence(post, prior).sum(-1)
            kl = torch.clamp(kl, min=self.cfg.kl_free).mean()
            kl_loss = kl_loss + kl
            prev_action = actions[:, t]

        loss = (recon_loss + rew_loss + cont_loss + self.cfg.kl_scale * kl_loss) / T
        opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.world.parameters(), self.cfg.grad_clip)
        opt.step()
        # 상상 시작점: 마지막 시퀀스의 posterior feat (detach)
        return torch.stack(feats, dim=1).reshape(B * T, -1).detach()

    # -- actor-critic (imagination) -----------------------------------------

    def _train_actor_critic(self, start_feats: torch.Tensor, opt: torch.optim.Optimizer) -> None:
        H = self.cfg.horizon
        # 상상 시작 잠재 (start_feats = [deter|stoch])
        deter = start_feats[:, : self.world.rssm.deter]
        stoch = start_feats[:, self.world.rssm.deter :]

        feats_seq, logp_seq, ent_seq, rew_seq, cont_seq, val_seq = [], [], [], [], [], []
        for _ in range(H):
            feat = self.world.rssm.feat(deter, stoch)
            logits = self.ac.actor(feat)
            dist = torch.distributions.Categorical(logits=logits)
            action = dist.sample()
            feats_seq.append(feat)
            logp_seq.append(dist.log_prob(action))
            ent_seq.append(dist.entropy())
            val_seq.append(self.ac.critic(feat).squeeze(-1))
            with torch.no_grad():
                rew_seq.append(symexp(self.world.reward(feat).squeeze(-1)))
                cont_seq.append(torch.sigmoid(self.world.cont(feat).squeeze(-1)))
            deter, stoch, _ = self.world.rssm.img_step(stoch, self._onehot(action), deter)
            deter, stoch = deter.detach(), stoch.detach()

        values = torch.stack(val_seq, dim=1)       # (N,H)
        rewards = torch.stack(rew_seq, dim=1)
        conts = torch.stack(cont_seq, dim=1) * self.cfg.gamma
        logps = torch.stack(logp_seq, dim=1)
        ents = torch.stack(ent_seq, dim=1)

        # λ-리턴 (DreamerV3 스타일, 뒤에서 앞으로)
        returns = torch.zeros_like(values)
        last = values[:, -1].detach()
        for t in reversed(range(H)):
            last = rewards[:, t] + conts[:, t] * (
                (1 - self.cfg.lam) * values[:, t].detach() + self.cfg.lam * last
            )
            returns[:, t] = last

        adv = (returns - values).detach()
        actor_loss = -(logps * adv).mean() - self.cfg.entropy_scale * ents.mean()
        critic_loss = F.mse_loss(values, returns.detach())
        loss = actor_loss + critic_loss

        opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.ac.parameters(), self.cfg.grad_clip)
        opt.step()

    # -- evaluation ----------------------------------------------------------

    def _evaluate(self, dataset, closes, feats, split) -> dict:
        """홀드아웃 구간에서 그리디 정책으로 백테스트 → 평가 지표."""
        hold_closes = closes[split - self.cfg.lookback :]
        hold_feats = [list(f) for f in feats[split - self.cfg.lookback :]] if feats else None
        if len(hold_closes) < self.cfg.lookback + 2:
            return _empty_eval()
        env = self.build_env(dataset, closes=hold_closes, features=hold_feats)
        obs, _ = env.reset()
        terminated = False
        steps = 0
        while not terminated and steps < len(env.closes):
            action = self._greedy_action(obs)
            obs, _r, terminated, _t, _info = env.step(action)
            steps += 1
        summ = env.get_episode_summary()
        approved = (
            summ["excess_return_pct"] > 0.0 and summ["max_drawdown_pct"] > -40.0
        )
        return {
            "total_return_pct": summ["total_return_pct"],
            "baseline_return_pct": summ["baseline_return_pct"],
            "excess_return_pct": summ["excess_return_pct"],
            "max_drawdown_pct": summ["max_drawdown_pct"],
            "trades": summ["total_trades"],
            "win_rate": summ["win_rate"],
            "holdout_steps": summ["steps"],
            "approved": bool(approved),
        }

    def _greedy_action(self, obs: np.ndarray) -> int:
        with torch.no_grad():
            t = torch.as_tensor(obs, dtype=torch.float32, device=self.device).unsqueeze(0)
            embed = self.world.rssm.embed(symlog(t))
            deter, stoch = self.world.rssm.initial(1, self.device)
            deter, stoch, _, _ = self.world.rssm.obs_step(
                stoch, torch.zeros(1, NUM_ACTIONS, device=self.device), deter, embed
            )
            logits = self.ac.actor(self.world.rssm.feat(deter, stoch))
            return int(torch.argmax(logits, dim=-1).item())

    # -- inference (공통 인터페이스용) ---------------------------------------

    def load_state(self, state_dict: dict, obs_dim: int) -> None:
        self.obs_dim = obs_dim
        self.world = WorldModel(obs_dim, NUM_ACTIONS, self.cfg).to(self.device)
        self.ac = ActorCritic(self.world.rssm.feat_dim, NUM_ACTIONS, self.cfg).to(self.device)
        self.world.load_state_dict(state_dict["world"])
        self.ac.load_state_dict(state_dict["ac"])
        self.world.eval()
        self.ac.eval()

    def act_from_window(self, closes, features, position: int) -> tuple[str, float]:
        """최근 윈도우로 잠재를 워밍업한 뒤 그리디 행동을 낸다."""
        cfg = TradingEnvConfig(
            closes=[float(c) for c in closes],
            intraday_features=[list(f) for f in features] if features else None,
            lookback=min(self.cfg.lookback, max(2, len(closes) - 2)),
        )
        env = TradingEnv(cfg)
        obs, _ = env.reset()
        with torch.no_grad():
            deter, stoch = self.world.rssm.initial(1, self.device)
            prev_action = torch.zeros(1, NUM_ACTIONS, device=self.device)
            terminated = False
            steps = 0
            logits = None
            while not terminated and steps < len(env.closes):
                t = torch.as_tensor(obs, dtype=torch.float32, device=self.device).unsqueeze(0)
                embed = self.world.rssm.embed(symlog(t))
                deter, stoch, _, _ = self.world.rssm.obs_step(stoch, prev_action, deter, embed)
                logits = self.ac.actor(self.world.rssm.feat(deter, stoch))
                action = int(torch.argmax(logits, dim=-1).item())
                prev_action = self._onehot(torch.tensor([action]))
                obs, _r, terminated, _t, _info = env.step(action)
                steps += 1
            if logits is None:
                return "HOLD", 0.34
            probs = torch.softmax(logits, dim=-1).squeeze(0)
            action = int(torch.argmax(probs).item())
            conf = float(min(0.98, max(0.34, probs[action].item())))
            return action_to_str(action), conf


def _empty_eval() -> dict:
    return {
        "total_return_pct": 0.0, "baseline_return_pct": 0.0, "excess_return_pct": 0.0,
        "max_drawdown_pct": 0.0, "trades": 0, "win_rate": 0.0, "holdout_steps": 0,
        "approved": False,
    }


def save_dreamer_checkpoint(path: str, train_result: dict) -> None:
    """train() 결과를 torch 체크포인트로 저장한다(state_dict+obs_dim+config)."""
    torch.save(
        {
            "state_dict": train_result["state_dict"],
            "obs_dim": train_result["obs_dim"],
            "config": train_result.get("config", {}),
        },
        path,
    )


class DreamerRLPolicy:
    """DreamerV3 정책의 공통 인터페이스(RLPolicy) 어댑터.

    artifact.model_path 의 torch 체크포인트를 로드해 잠재 워밍업 후 그리디 행동을 낸다.
    """

    algorithm = "dreamer_v3"

    def __init__(self, artifact: Any) -> None:
        if not getattr(artifact, "model_path", None):
            raise ValueError(
                f"DreamerV3 정책에 model_path 가 없습니다: policy_id={getattr(artifact, 'policy_id', '?')}"
            )
        ckpt = torch.load(artifact.model_path, map_location="cpu", weights_only=False)
        cfg = DreamerConfig(**ckpt["config"]) if ckpt.get("config") else DreamerConfig()
        self._trainer = DreamerV3Trainer(cfg=cfg)
        self._trainer.load_state(ckpt["state_dict"], int(ckpt["obs_dim"]))

    def act(self, closes, *, position: int = 0, features=None):
        from src.agents.rl_policy_interface import PolicyDecision

        # combined 로 학습된 정책 (obs_dim > DEFAULT_DAILY_OBS_DIM) 인데 호출자가
        # features 를 안 넘긴 경우, 학습 시 마스킹 semantics 와 동일하게 zero-mask
        # 로 채워 shape mismatch 를 방지한다. Runner 가 아직 combined-aware 이지
        # 않을 때의 방어망 (Option A). Runner 가 실 features 를 넘기면 그대로 사용.
        if features is None and self._trainer.obs_dim is not None:
            from src.agents.rl_environment import DEFAULT_DAILY_OBS_DIM

            needed = int(self._trainer.obs_dim) - DEFAULT_DAILY_OBS_DIM
            if needed > 0:
                features = [[0.0] * needed for _ in closes]

        action, conf = self._trainer.act_from_window(closes, features, position)
        return PolicyDecision(
            action=action, confidence=conf, meta={"algorithm": self.algorithm}
        )
