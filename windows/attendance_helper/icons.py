# Copyright (c) iGroup China.
# All rights reserved.
"""
托盘状态图标与可选饼图绘制。

@author Kai
@date 2026/08/05 14:15
@description 托盘用状态色点/符号；含角色情绪 tone
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap


def tone_color(tone: str) -> QColor:
    """
    状态色（与详情卡一致）。

    @param tone normal / near / done / error / paused / token / hurry / ready / overtime / celebrate / idle
    @return 填充色
    @author Kai
    @date 2026/08/05 14:15
    """
    if tone in ("done", "ready", "celebrate"):
        return QColor("#22C55E")
    if tone in ("near", "hurry"):
        return QColor("#F59E0B")
    if tone == "overtime":
        return QColor("#F97316")
    if tone in ("error", "token"):
        return QColor("#EF4444")
    if tone == "paused":
        return QColor("#9CA3AF")
    return QColor("#4FD1A5")


def resolve_persona_tone(
    base_tone: str,
    *,
    open_items: int = 0,
    celebrating: bool = False,
    overtime: bool = False,
) -> str:
    """
    将考勤 tone 与事项状态合成托盘角色情绪。

    @param base_tone 考勤基础 tone
    @param open_items 未完成事项数
    @param celebrating 是否庆祝中
    @param overtime 是否加班态
    @return 角色 tone
    @author Kai
    @date 2026/08/05 14:15
    """
    if celebrating:
        return "celebrate"
    if base_tone in ("error", "token", "paused"):
        return base_tone
    if overtime or base_tone == "overtime":
        return "overtime"
    if base_tone == "done" and open_items <= 0:
        return "ready"
    if base_tone in ("near", "done") and open_items > 0:
        return "hurry"
    if base_tone == "done":
        return "ready"
    if base_tone == "near":
        return "near"
    return "idle"


def paint_pie(
    painter: QPainter,
    rect: QRectF,
    progress: float,
    tone: str = "normal",
    *,
    show_percent: bool = True,
    hole_ratio: float = 0.55,
) -> None:
    """
    在指定矩形内绘制环形饼图（保留给其它 UI 复用）。

    @param painter 画笔
    @param rect 外接矩形
    @param progress 0~1
    @param tone 色调
    @param show_percent 是否显示中心百分比
    @param hole_ratio 中心挖空比例
    @author Kai
    @date 2026/07/23 15:25
    """
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)

    track = QColor(255, 255, 255, 55)
    fill = tone_color(tone)
    p = max(0.0, min(1.0, float(progress)))

    painter.setBrush(track)
    painter.drawEllipse(rect)

    if p > 0.0001:
        painter.setBrush(fill)
        start = 90 * 16
        span = -int(p * 360 * 16)
        painter.drawPie(rect, start, span)

    margin = rect.width() * (1.0 - hole_ratio) / 2.0
    hole = rect.adjusted(margin, margin, -margin, -margin)
    painter.setBrush(QColor(22, 26, 34, 235))
    painter.drawEllipse(hole)

    if show_percent:
        pct = int(round(p * 100))
        painter.setPen(QColor(255, 255, 255))
        size = 14 if rect.width() >= 56 else 11
        if pct >= 100:
            size = max(10, size - 2)
        painter.setFont(QFont("Segoe UI", size, QFont.Weight.Bold))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), f"{pct}")
    painter.restore()


def _draw_check(painter: QPainter, cx: float, cy: float, r: float, color: QColor) -> None:
    """绘制勾选符号圆。"""
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QPointF(cx, cy), r, r)
    pen = QPen(QColor("#0B1F14"), max(2.5, r * 0.22))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    path = QPainterPath()
    path.moveTo(cx - r * 0.45, cy + r * 0.05)
    path.lineTo(cx - r * 0.1, cy + r * 0.4)
    path.lineTo(cx + r * 0.5, cy - r * 0.35)
    painter.drawPath(path)


def paint_status_glyph(
    painter: QPainter,
    rect: QRectF,
    tone: str = "normal",
) -> None:
    """
    绘制托盘状态符号（色点 / 勾 / 叹号 / 锁 / 暂停 / 角色态）。

    @param painter 画笔
    @param rect 外接矩形
    @param tone 状态
    @author Kai
    @date 2026/08/05 14:15
    """
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = tone_color(tone)
    cx = rect.center().x()
    cy = rect.center().y()
    r = min(rect.width(), rect.height()) * 0.34

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(22, 26, 34, 220))
    painter.drawEllipse(rect.adjusted(4, 4, -4, -4))

    if tone in ("done", "ready", "celebrate"):
        _draw_check(painter, cx, cy, r, color)
        if tone == "celebrate":
            # 外圈高亮表示庆祝
            painter.setPen(QPen(QColor("#86EFAC"), max(2.0, r * 0.12)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), r * 1.25, r * 1.25)
    elif tone == "token":
        painter.setBrush(color)
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.setPen(QPen(QColor("#FFFFFF"), max(2.0, r * 0.14)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(
            QRectF(cx - r * 0.28, cy - r * 0.42, r * 0.56, r * 0.5),
            0,
            180 * 16,
        )
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(
            QRectF(cx - r * 0.32, cy - r * 0.05, r * 0.64, r * 0.48), 3, 3
        )
        painter.setBrush(color)
        painter.drawEllipse(QPointF(cx, cy + r * 0.12), r * 0.1, r * 0.1)
    elif tone == "error":
        painter.setBrush(color)
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.setPen(QPen(QColor("#FFFFFF"), max(2.0, r * 0.18)))
        painter.drawLine(
            QPointF(cx, cy - r * 0.4),
            QPointF(cx, cy + r * 0.05),
        )
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy + r * 0.38), r * 0.12, r * 0.12)
    elif tone == "paused":
        painter.setBrush(color)
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(Qt.PenStyle.NoPen)
        w = r * 0.18
        h = r * 0.7
        gap = r * 0.18
        painter.drawRoundedRect(
            QRectF(cx - gap - w, cy - h / 2, w, h), 1.5, 1.5
        )
        painter.drawRoundedRect(
            QRectF(cx + gap, cy - h / 2, w, h), 1.5, 1.5
        )
    elif tone in ("hurry", "overtime"):
        # 感叹强调
        painter.setBrush(color)
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.setPen(QPen(QColor("#FFFFFF"), max(2.0, r * 0.18)))
        painter.drawLine(
            QPointF(cx, cy - r * 0.4),
            QPointF(cx, cy + r * 0.05),
        )
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy + r * 0.38), r * 0.12, r * 0.12)
    else:
        # idle / near / normal
        painter.setBrush(color)
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.setBrush(QColor(255, 255, 255, 55))
        painter.drawEllipse(
            QPointF(cx - r * 0.25, cy - r * 0.28), r * 0.28, r * 0.22
        )

    painter.restore()


def make_tray_icon(progress: float = 0.0, tone: str = "normal") -> QIcon:
    """
    生成托盘状态图标（色点/符号，不显示百分比）。

    @param progress 保留参数兼容旧调用（忽略）
    @param tone 状态色
    @return QIcon
    @author Kai
    @date 2026/08/05 14:15
    """
    _ = progress
    size = 64
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    paint_status_glyph(painter, QRectF(4, 4, size - 8, size - 8), tone)
    painter.end()
    return QIcon(pix)
