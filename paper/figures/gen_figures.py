"""生成 UserSim 论文图 1（motivation）与图 2（系统架构）。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(sys.executable).parent.parent.parent))
from daimon_runtime import setup_plot
setup_plot()

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = Path("/Users/webdrag0n/Desktop/UserSim/usersim/paper/figures")
OUT.mkdir(parents=True, exist_ok=True)

INK = "#222222"
GREY = "#8a8a8a"
ACCENT = "#2c6fbb"
RULE_BG = "#f4f6f8"
LLM_BG = "#fdf6ec"

# ---------------------------------------------------------------- 图 1
fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.0))

ax = axes[0]
ax.set_title("静态数据集：一条预设路径", fontsize=13, color=INK, pad=10)
xs = [0.5 + i * 1.0 for i in range(6)]
for i, x in enumerate(xs):
    ax.scatter(x, 0, s=130, color="white", edgecolor=GREY, zorder=3, linewidth=1.4)
    if i < len(xs) - 1:
        ax.annotate("", xy=(xs[i + 1] - 0.14, 0), xytext=(x + 0.14, 0),
                    arrowprops=dict(arrowstyle="-", color=GREY, lw=1.4))
for i, lab in enumerate(["问", "答", "问", "答", "问", "答"]):
    ax.text(xs[i], 0, lab, ha="center", va="center", fontsize=9, color=INK, zorder=4)
ax.annotate("轮次增加", xy=(xs[-1] + 0.7, 0), xytext=(xs[-1] + 0.55, 0),
            arrowprops=dict(arrowstyle="->", color=GREY, lw=1.2), fontsize=10, color=GREY, va="center")
ax.text(sum(xs[:3]) / 3, 0.55, "路径固定，参考答案唯一", ha="center", fontsize=10.5, color=GREY)
ax.text(sum(xs) / len(xs), -0.62, "无法覆盖真实交互的分支多样性", ha="center", fontsize=10.5, color=ACCENT)
ax.set_xlim(0, 7.2); ax.set_ylim(-1.1, 1.1); ax.axis("off")

ax = axes[1]
ax.set_title("真实长程交互：不断分岔的决策树", fontsize=13, color=INK, pad=10)

def tree(x, y, dx, depth, path):
    if depth == 0:
        return
    n = 2 if depth > 1 else 3
    for i in range(n):
        cxx = x + 1.15
        cyy = y + (i - (n - 1) / 2) * dx
        on_path = path and i == 0
        ax.plot([x, cxx], [y, cyy], color=ACCENT if on_path else GREY,
                lw=1.8 if on_path else 1.0, zorder=2)
        ax.scatter(cxx, cyy, s=95, color="white",
                   edgecolor=ACCENT if on_path else GREY, zorder=3,
                   linewidth=1.6 if on_path else 1.1)
        tree(cxx, cyy, dx * 0.52, depth - 1, on_path)

ax.scatter(0, 0, s=110, color="white", edgecolor=ACCENT, zorder=3, linewidth=1.6)
tree(0, 0, 1.5, 3, True)
ax.text(1.0, 1.66, "用户人格与状态不同", fontsize=9.5, color=GREY, ha="left")
ax.text(0.9, -1.95, "同一句话，不同回应", fontsize=9.5, color=GREY, ha="left")
ax.text(3.55, -1.35, "实际轨迹\n（其中一条）", fontsize=9.5, color=ACCENT, ha="left", va="center")
ax.set_xlim(-0.4, 5.0); ax.set_ylim(-2.2, 2.2); ax.axis("off")

fig.savefig(OUT / "fig1_motivation.png", dpi=220, bbox_inches="tight")
plt.close(fig)

# ---------------------------------------------------------------- 图 2
fig, ax = plt.subplots(figsize=(11.5, 7.2))
ax.set_xlim(0, 100); ax.set_ylim(0, 66); ax.axis("off")

def box(x, y, w, h, text, fc, ec=GREY, fs=10, lw=1.3):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6,rounding_size=1.2",
                                fc=fc, ec=ec, lw=lw, zorder=2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=INK, zorder=3)

def arrow(x1, y1, x2, y2, color=INK, ls="-", lw=1.4):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=13,
                                 color=color, lw=lw, linestyle=ls, zorder=4,
                                 shrinkA=2, shrinkB=2))

# 规则世界（0 LLM）
ax.add_patch(FancyBboxPatch((2, 32), 68, 32, boxstyle="round,pad=0.8,rounding_size=1.5",
                            fc=RULE_BG, ec=GREY, lw=1.4, zorder=1))
ax.text(5, 62.5, "规则世界 · 0 次 LLM 调用", fontsize=12, color=INK, weight="bold", va="center")

box(5, 50, 14, 8, "时钟 / 日历\n双层时钟", "white")
box(21, 50, 24, 8, "事件引擎\n作息模板 ⊕ 泊松扰动 ⊕ 用户新增", "white", fs=9.5)
box(47, 50, 20, 8, "天气 / 经济\n马尔可夫天气 · 收支结算", "white", fs=9.5)
box(5, 36, 30, 10, "状态动力学（唯一写入方）\nx(t+1) = A·x + B·u + D·d + ε\n习惯化 · 需求 · 峰终 / 消极偏向", "white", fs=9.5)
box(37, 36, 30, 10, "日程 / 事件裁决\n工具调用的唯一生效通道", "white", fs=9.5)

# 评估器（0 LLM）
ax.add_patch(FancyBboxPatch((74, 32), 24, 32, boxstyle="round,pad=0.8,rounding_size=1.5",
                            fc=RULE_BG, ec=GREY, lw=1.4, zorder=1))
ax.text(76, 62.5, "评估器 · 离线 · 0 LLM", fontsize=12, color=INK, weight="bold", va="center")
box(76, 36, 20, 24, "轨迹泛函\n\ne_ss · t_s · M_p\nIAE / ISE / ITAE\n带内驻留 · 判定\n$\\Vert x-\\hat{x}\\Vert$ · 画像精度\nM1–M5 质量门", "white", fs=9.5)

# LLM 区
ax.add_patch(FancyBboxPatch((2, 2), 96, 25, boxstyle="round,pad=0.8,rounding_size=1.5",
                            fc=LLM_BG, ec="#d9b36c", lw=1.4, zorder=1))
ax.text(5, 3.8, "LLM 只住在这里", fontsize=12, color="#8a6d1f", weight="bold", va="center")

box(8, 6, 34, 15, "用户 Agent（LLM）\n状态 → 表达 · 意图 · 求助决策\n看不到状态数值（felt_state）", "white", fs=10)
box(58, 6, 34, 15, "助手 Agent（LLM，被测件）\n回复 + user_belief $\\hat{x}$ + 工具调用\n经统一 agent 接口接入", "white", fs=10)

# 世界 ↔ 用户
arrow(14, 36, 14, 21.5)
ax.text(14, 24.3, "felt_state / 事件提示", fontsize=8.5, color=INK, ha="center")
arrow(34, 21.5, 34, 36)
ax.text(34, 24.3, "意图 · 新增事件", fontsize=8.5, color=INK, ha="center")
# 用户 ↔ 助手
arrow(42.5, 13.5, 57.5, 13.5)
ax.text(50, 15.8, "对话", fontsize=9, color=INK, ha="center")
# 助手 ↔ 世界
arrow(66, 21.5, 66, 36)
ax.text(66, 24.3, "工具调用", fontsize=8.5, color=INK, ha="center")
arrow(84, 36, 84, 21.5)
ax.text(84, 24.3, "工具结果", fontsize=8.5, color=INK, ha="center")

# 结构化日志 → 评估器
ax.add_patch(FancyArrowPatch((55, 30.5), (82, 35.5), arrowstyle="-|>", mutation_scale=13,
                             color=GREY, lw=1.3, linestyle="--", zorder=4,
                             connectionstyle="arc3,rad=-0.15", shrinkA=0, shrinkB=2))
ax.text(63, 33.4, "结构化日志（JSONL）", fontsize=9, color=GREY, ha="center", va="center")

# LLM 边界
ax.plot([1, 99], [29.5, 29.5], color="#c0392b", lw=1.6, ls=(0, (6, 4)), zorder=5)
ax.text(50, 29.5, " LLM 边界：线上 0 次 LLM 调用，线下仅两个 Agent ", fontsize=10.5,
        color="#c0392b", ha="center", va="center",
        bbox=dict(fc="white", ec="#c0392b", lw=0.8, pad=2))

fig.savefig(OUT / "fig2_architecture.png", dpi=220, bbox_inches="tight")
plt.close(fig)

print("saved:", [p.name for p in OUT.glob("*.png")])
