# Copyright (c) iGroup.
# All rights reserved.
"""
电子木鱼按钮与短暂的功德飘字。

@author Kai
@date 2026/10/15 16:11
@description 使用原生绘制与动画，默认静音，不产生额外窗口
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEasingCurve, QPoint, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QWidget

from ..config import S
from ..relaxation import knock_woodfish, merit_snapshot, play_woodfish_sound


class WoodfishButton(QPushButton):
    """
    宠物旁可重复点击的小木鱼。

    @author Kai
    @date 2026/10/15 16:11
    @description 按一次记一次，动画和音效均不改变真实倒计时
    """

    # 父卡片只接收今日和累计次数，用来展示临时反馈。
    knocked = Signal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        """
        创建可访问的木鱼按钮和回弹动画。

        @param parent 所属详情卡
        @author Kai
        @date 2026/10/15 16:11
        """
        super().__init__(parent)
        # 冲击进度只影响绘制缩放，不修改布局和命中区域。
        self._impact = 0.0
        self.setFixedSize(30, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("敲木鱼")
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(180)
        self._animation.setStartValue(1.0)
        self._animation.setEndValue(0.0)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._animate)
        self.clicked.connect(self._knock)
        self.refresh_count()

    def refresh_count(self) -> None:
        """
        更新悬停提示里的今日与累计敲击次数。

        @author Kai
        @date 2026/10/15 16:11
        """
        counts = merit_snapshot()
        self.setToolTip(f"敲木鱼 · 今日 {counts['today']} 次 / 累计 {counts['total']} 次")

    def _knock(self) -> None:
        """
        保存主动点击，按设置播放声音并通知父卡片飘字。

        @author Kai
        @date 2026/10/15 16:11
        """
        if not (S.fun_enable and S.fun_pet_enable and S.fun_woodfish_enable):
            return
        counts = knock_woodfish()
        self.refresh_count()
        self._animation.stop()
        self._animation.start()
        if S.fun_woodfish_sound:
            play_woodfish_sound()
        self.knocked.emit(counts["today"], counts["total"])

    def _animate(self, value: Any) -> None:
        """
        推进敲击回弹的绘制状态。

        @param value 当前冲击进度
        @author Kai
        @date 2026/10/15 16:11
        """
        self._impact = float(value)
        self.update()

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        """
        绘制木鱼、裂口与木槌，不依赖图片素材。

        @param event Qt 重绘事件
        @author Kai
        @date 2026/10/15 16:11
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(15, 14)
        scale = 1.0 - self._impact * 0.12
        painter.scale(scale, scale)
        painter.setPen(QPen(QColor("#A76E36"), 1))
        painter.setBrush(QColor("#E5B77B") if self.underMouse() else QColor("#C99A64"))
        painter.drawEllipse(QRectF(-12, -6, 23, 16))
        painter.setPen(QPen(QColor("#634127"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(QRectF(-7, -2, 14, 6), 10 * 16, 165 * 16)
        painter.drawLine(0, -1, 6, 4)
        painter.setPen(QPen(QColor("#DDB37B"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(1, -11, 11, -5)
        painter.setBrush(QColor("#F1D1A3"))
        painter.drawEllipse(QRectF(-2, -13, 6, 5))


class MeritFloat(QWidget):
    """
    卡片内部短暂上浮的“功德 +1”。

    @author Kai
    @date 2026/10/15 16:11
    @description 重复点击重启同一个特效，隐藏后释放动画，不创建新窗口
    """

    def __init__(self, parent: QWidget) -> None:
        """
        创建不拦截鼠标的透明飘字层。

        @param parent 所属详情卡
        @author Kai
        @date 2026/10/15 16:11
        """
        super().__init__(parent)
        # 进度控制透明度和位移，原点由宠物位置决定。
        self._progress = 0.0
        self._origin = QPoint()
        self.setFixedSize(82, 22)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(650)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.valueChanged.connect(self._animate)
        self._animation.finished.connect(self.hide)
        self.hide()

    def pop(self, origin: QPoint) -> None:
        """
        从指定位置重新播放一次飘字。

        @param origin 动画起点，相对详情卡左上角
        @author Kai
        @date 2026/10/15 16:11
        """
        self._animation.stop()
        self._origin = origin
        self._progress = 0.0
        self.move(origin)
        self.show()
        self.raise_()
        self._animation.start()

    def stop(self) -> None:
        """
        隐藏卡片时停止飘字动画。

        @author Kai
        @date 2026/10/15 16:11
        """
        self._animation.stop()
        self.hide()

    def _animate(self, value: Any) -> None:
        """
        推进位移与透明度。

        @param value 动画完成比例
        @author Kai
        @date 2026/10/15 16:11
        """
        self._progress = float(value)
        self.move(self._origin + QPoint(0, -int(self._progress * 18)))
        self.update()

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        """
        绘制随时间淡出的功德提示。

        @param event Qt 重绘事件
        @author Kai
        @date 2026/10/15 16:11
        """
        painter = QPainter(self)
        color = QColor("#F3D49A")
        color.setAlpha(int(255 * (1.0 - self._progress)))
        painter.setPen(color)
        painter.setFont(QFont("Microsoft YaHei UI", 10, QFont.Weight.DemiBold))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "功德 +1")
