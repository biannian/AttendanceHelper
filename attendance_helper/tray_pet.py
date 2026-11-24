# Copyright (c) iGroup China.
# All rights reserved.
"""
托盘宠物：SpriteSheet 像素动画系统。

@author Kai
@date 2026/08/05 17:19
@description 16x8 柴犬 spritesheet；QTimer 驱动状态帧动画
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, QRect, QRectF, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from .attendance import AttendanceSummary
from .config import S
from .paths import RESOURCE_ROOT, ROOT

# 宠物目前只保留 spritesheet 柴犬，配置里其它值统一归一到 shiba。
PET_SHIBA = "shiba"
PET_CAT = PET_SHIBA
PET_CAPYBARA = PET_SHIBA
PET_ROBOT = PET_SHIBA
PET_PIXEL = PET_SHIBA
PET_GEO = PET_SHIBA

PET_LABELS: dict[str, str] = {
    PET_SHIBA: "像素柴犬",
}

# 宠物情绪 / 动作
MOOD_IDLE = "idle"
MOOD_YAWN = "yawn"
MOOD_TYPE = "type"
MOOD_STRETCH = "stretch"
MOOD_PACK = "pack"
MOOD_WATCH = "watch"
MOOD_WAVE = "wave"
MOOD_COOL = "cool"
MOOD_HYPE = "hype"

# spritesheet 规格：16 列 x 8 行；优先播放预切片帧，缺省再回退整图切片。
# FALLBACK_SPRITE_SIZE 仅在缺图兜底时使用，与真实单格尺寸无关。
FALLBACK_SPRITE_SIZE = 128
SPRITE_COLUMNS = 16
SPRITE_ROWS = 8
SPRITE_FILE = "dog16-v3.png"
# 预切片目录：pet/frames/<mood>/00.png … 15.png
SPRITE_FRAMES_DIR = "frames"

# 行号：一行一种动作，每行 16 帧（列 0..15）。
MOOD_ROWS: dict[str, int] = {
    MOOD_YAWN: 0,       # 刚上班：打哈欠
    MOOD_TYPE: 1,       # 工作中：敲键盘
    MOOD_IDLE: 1,       # 空闲默认走工作中待机动画
    MOOD_STRETCH: 2,    # 摸鱼：玩手机
    MOOD_WATCH: 3,      # 距离下班 3 小时：看时间
    MOOD_PACK: 4,       # 距离下班 30 分钟：收拾东西
    MOOD_COOL: 5,       # 下班：欢呼
    MOOD_WAVE: 6,       # 忘记打卡：哭
    MOOD_HYPE: 7,       # 周五：狂欢
}

# 行序对应的动作目录名（与 MOOD_ROWS 一致，idle 复用 type）。
ROW_MOOD_DIRS: list[str] = [
    MOOD_YAWN,
    MOOD_TYPE,
    MOOD_STRETCH,
    MOOD_WATCH,
    MOOD_PACK,
    MOOD_COOL,
    MOOD_WAVE,
    MOOD_HYPE,
]

# 详情卡动画帧间隔（任务栏图标另有节流，避免小图标闪得过快）。
MOOD_INTERVALS_MS: dict[str, int] = {
    MOOD_IDLE: 140,
    MOOD_YAWN: 130,
    MOOD_TYPE: 110,
    MOOD_STRETCH: 125,
    MOOD_WATCH: 150,
    MOOD_PACK: 120,
    MOOD_WAVE: 130,
    MOOD_COOL: 100,
    MOOD_HYPE: 85,
}

# 任务栏图标最小换帧间隔：小尺寸图标不需要详情卡那么高的帧率。
TRAY_ICON_MIN_INTERVAL_MS = 280


def normalize_pet(raw: str) -> str:
    """
    规范化宠物 id。

    @param raw 配置中的宠物值
    @return 目前固定为 shiba
    @author Kai
    @date 2026/08/05 17:19
    """
    _ = raw
    return PET_SHIBA


def resolve_pet_mood(
    summary: AttendanceSummary,
    *,
    now: Optional[datetime] = None,
) -> str:
    """
    根据考勤摘要解析宠物情绪。

    @param summary 摘要
    @param now 当前时间
    @return mood id
    @author Kai
    @date 2026/08/05 15:03
    """
    now = now or datetime.now()
    if not summary.ok and summary.error != "NON_WORKDAY":
        return MOOD_WAVE
    if summary.token_expired:
        return MOOD_WAVE
    if not summary.has_clock_in:
        return MOOD_WAVE
    if summary.target_reached and summary.has_clock_out:
        return MOOD_COOL
    if summary.target_reached:
        return MOOD_PACK
    remain = max(0, int(summary.remaining_seconds))
    worked = max(0, int(summary.worked_seconds))
    if remain <= 20 * 60:
        return MOOD_PACK
    if now.weekday() == 4 and remain <= 2 * 3600:
        return MOOD_HYPE
    if worked >= 6 * 3600 and remain > 30 * 60:
        return MOOD_STRETCH
    if now.hour < 10 and worked < 3600:
        return MOOD_YAWN
    if remain > 3 * 3600:
        return MOOD_WATCH if now.hour >= 15 else MOOD_TYPE
    return MOOD_TYPE


def _pet_root_candidates() -> list[Path]:
    """
    返回宠物资源根目录候选（含 frames/ 与整图）。

    @return 候选目录列表
    @author Kai
    @date 2026/08/06 09:54
    """
    package_dir = Path(__file__).resolve().parent
    return [
        package_dir / "pet",
        RESOURCE_ROOT / "attendance_helper" / "pet",
        RESOURCE_ROOT / "pet",
        ROOT / "attendance_helper" / "pet",
        ROOT / "pet",
    ]


def _asset_candidates() -> list[Path]:
    """
    返回 spritesheet 整图可能位置。

    @return 候选路径列表
    @author Kai
    @date 2026/08/06 09:54
    """
    return [root / SPRITE_FILE for root in _pet_root_candidates()]


def _mood_frame_dir(mood: str) -> Optional[Path]:
    """
    定位某个动作的预切片帧目录。

    @param mood 动作 id（idle 映射到 type）
    @return 含 00.png… 的目录；找不到则 None
    @author Kai
    @date 2026/08/06 09:54
    """
    key = mood if mood in MOOD_ROWS else MOOD_IDLE
    row = MOOD_ROWS.get(key, MOOD_ROWS[MOOD_IDLE])
    dirname = ROW_MOOD_DIRS[row] if 0 <= row < len(ROW_MOOD_DIRS) else MOOD_TYPE
    for root in _pet_root_candidates():
        folder = root / SPRITE_FRAMES_DIR / dirname
        sample = folder / "00.png"
        if sample.exists():
            return folder
    return None


# 色键去背：只抠真正的洋红底，避免误伤奶油脸/橙色毛。
CHROMA_KEY_COLOR = QColor(255, 0, 255)
# dog16-v3 背景常见 (240,64,240) 一带，ΔG≈64–80。
CHROMA_KEY_TOLERANCE = 85


def _rgb_channel_delta(a: QColor, b: QColor) -> int:
    """
    计算两色 RGB 单通道最大绝对差（切比雪夫距离）。

    @param a 颜色 A
    @param b 颜色 B
    @return max(|ΔR|, |ΔG|, |ΔB|)
    @author Kai
    @date 2026/08/06 09:54
    """
    return max(
        abs(a.red() - b.red()),
        abs(a.green() - b.green()),
        abs(a.blue() - b.blue()),
    )


def _is_warm_fur(color: QColor) -> bool:
    """
    是否为角色暖色毛发/奶油脸（绝不能当背景清掉）。

    要求 B 明显低于 G，避免把品红粉边误判成毛发。

    @param color 像素色
    @return True 表示保底保留
    @author Kai
    @date 2026/08/06 10:17
    """
    red = color.red()
    green = color.green()
    blue = color.blue()
    # 奶油脸 / 橙色毛：偏暖，蓝通道明显低于绿。
    if red >= 160 and green >= 90 and blue <= green - 8 and red >= blue + 40:
        return True
    # 近白高光
    if red >= 220 and green >= 220 and blue >= 200:
        return True
    return False


def _is_magenta_bg(color: QColor, key: QColor, tolerance: int) -> bool:
    """
    判断是否为洋红背景（必须高 R 高 B、G 明显偏低）。

    @param color 像素色
    @param key 色键色
    @param tolerance RGB 容差
    @return True 表示背景
    @author Kai
    @date 2026/08/06 10:09
    """
    if color.alpha() == 0:
        return False
    if _is_warm_fur(color):
        return False
    red = color.red()
    green = color.green()
    blue = color.blue()
    # 核心约束：洋红签名，防止奶油/橙色被容差误伤。
    if green >= min(red, blue) - 25:
        return False
    if red < 150 or blue < 150:
        return False
    if (red + blue) / 2.0 - green < 50:
        return False
    return _rgb_channel_delta(color, key) <= tolerance or (
        red >= 190 and blue >= 180 and green <= 120
    )


def _is_pink_fringe(color: QColor) -> bool:
    """
    黑线外淡粉/品红晕（含中等亮度溢色，如 248,104,136）。

    橙色毛 B 远低于 G，不会命中。

    @param color 像素色
    @return True 表示应清掉的粉边
    @author Kai
    @date 2026/08/06 10:17
    """
    if color.alpha() == 0 or _is_warm_fur(color):
        return False
    red = color.red()
    green = color.green()
    blue = color.blue()
    # R、B 同时明显高于 G → 品红/淡紫晕
    if red >= green + 35 and blue >= green + 35:
        return True
    # 亮粉边：R 很高、B 中高、G 偏低（抗锯齿混色）
    if red >= 180 and blue >= 95 and green <= 145 and blue >= green + 15:
        if red >= green + 35:
            return True
    # 暗紫描边外晕
    peak = max(red, green, blue)
    if peak <= 120 and red >= green + 8 and blue >= green + 8:
        return True
    return False


def _despill_edge(color: QColor) -> QColor:
    """
    清理贴边粉晕，不动橙色/奶油色。

    @param color 边缘像素
    @return 处理后颜色
    @author Kai
    @date 2026/08/06 10:17
    """
    if _is_warm_fur(color):
        return color
    if _is_pink_fringe(color):
        return QColor(0, 0, 0, 0)
    red = color.red()
    green = color.green()
    blue = color.blue()
    alpha = color.alpha()
    peak = max(red, green, blue)
    # 轻微压暗描边偏色
    if peak <= 90 and (red > green or blue > green):
        v = min(red, green, blue)
        return QColor(v, v, v, alpha)
    return color


def _remove_orphan_top_strips(image: QImage) -> None:
    """
    去掉等分切片从上一切进来的桌沿等碎块（就地修改）。

    保留面积最大的主体，以及紧贴主体的小碎片（纸屑等）；
    清掉贴顶边且偏矮的独立连通域。

    @param image ARGB 图像
    @author Kai
    @date 2026/08/06 10:09
    """
    width = image.width()
    height = image.height()
    if width <= 0 or height <= 0:
        return
    labels = [-1] * (width * height)
    components: list[dict[str, int]] = []
    for y in range(height):
        for x in range(width):
            idx = y * width + x
            if labels[idx] != -1 or image.pixelColor(x, y).alpha() == 0:
                continue
            cid = len(components)
            stack = [(x, y)]
            labels[idx] = cid
            area = 0
            min_y = max_y = y
            touch_top = y == 0
            while stack:
                cx, cy = stack.pop()
                area += 1
                if cy < min_y:
                    min_y = cy
                if cy > max_y:
                    max_y = cy
                if cy == 0:
                    touch_top = True
                for nx, ny in (
                    (cx - 1, cy),
                    (cx + 1, cy),
                    (cx, cy - 1),
                    (cx, cy + 1),
                ):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    nidx = ny * width + nx
                    if labels[nidx] != -1:
                        continue
                    if image.pixelColor(nx, ny).alpha() == 0:
                        continue
                    labels[nidx] = cid
                    stack.append((nx, ny))
            components.append(
                {
                    "area": area,
                    "min_y": min_y,
                    "max_y": max_y,
                    "touch_top": int(touch_top),
                }
            )
    if not components:
        return
    main_id = max(range(len(components)), key=lambda i: components[i]["area"])
    main = components[main_id]
    # 与主体垂直方向重叠或贴近的碎片保留（hype 彩纸）。
    keep = {main_id}
    for i, comp in enumerate(components):
        if i == main_id:
            continue
        # 贴顶且高度很矮：上一行桌沿
        comp_h = comp["max_y"] - comp["min_y"] + 1
        if comp["touch_top"] and comp_h <= max(28, height // 10):
            continue
        if comp["touch_top"] and comp["max_y"] < main["min_y"] - 2:
            continue
        # 主体附近的小碎片
        if abs(comp["min_y"] - main["min_y"]) <= 80 or (
            comp["min_y"] <= main["max_y"] and comp["max_y"] >= main["min_y"]
        ):
            keep.add(i)
    for y in range(height):
        for x in range(width):
            idx = y * width + x
            cid = labels[idx]
            if cid >= 0 and cid not in keep:
                image.setPixelColor(x, y, QColor(0, 0, 0, 0))


def make_sheet_background_transparent(
    pixmap: QPixmap,
    *,
    key: QColor = CHROMA_KEY_COLOR,
    tolerance: int = CHROMA_KEY_TOLERANCE,
) -> QPixmap:
    """
    洋红色键去背：保暖色毛发，并去掉顶边串进来的桌沿。

    @param pixmap 原始图
    @param key 色键颜色，默认 #FF00FF
    @param tolerance RGB 单通道色差容差
    @return 带透明通道的 QPixmap
    @author Kai
    @date 2026/08/06 10:09
    """
    if pixmap.isNull():
        return pixmap
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    width = image.width()
    height = image.height()
    if width <= 0 or height <= 0:
        return pixmap

    limit = max(0, int(tolerance))
    visited = bytearray(width * height)
    stack: list[tuple[int, int]] = []

    def _try_seed(x: int, y: int) -> None:
        """画布边缘的洋红像素入队。"""
        if _is_magenta_bg(image.pixelColor(x, y), key, limit):
            stack.append((x, y))

    for x in range(width):
        _try_seed(x, 0)
        _try_seed(x, height - 1)
    for y in range(height):
        _try_seed(0, y)
        _try_seed(width - 1, y)

    while stack:
        x, y = stack.pop()
        index = y * width + x
        if visited[index]:
            continue
        visited[index] = 1
        if not _is_magenta_bg(image.pixelColor(x, y), key, limit):
            continue
        image.setPixelColor(x, y, QColor(0, 0, 0, 0))
        if x > 0:
            stack.append((x - 1, y))
        if x + 1 < width:
            stack.append((x + 1, y))
        if y > 0:
            stack.append((x, y - 1))
        if y + 1 < height:
            stack.append((x, y + 1))

    # 封闭品红小洞（尾巴夹角），仍受暖色保护。
    for y in range(height):
        for x in range(width):
            color = image.pixelColor(x, y)
            if _is_magenta_bg(color, key, limit) and color.red() >= 200:
                image.setPixelColor(x, y, QColor(0, 0, 0, 0))

    # 贴边粉晕多轮收缩（含中等亮度品红边，不动橙色/奶油）。
    for _ in range(5):
        changed = False
        for y in range(height):
            for x in range(width):
                color = image.pixelColor(x, y)
                if color.alpha() == 0 or _is_warm_fur(color):
                    continue
                near_clear = False
                for nx, ny in (
                    (x - 1, y),
                    (x + 1, y),
                    (x, y - 1),
                    (x, y + 1),
                    (x - 1, y - 1),
                    (x + 1, y - 1),
                    (x - 1, y + 1),
                    (x + 1, y + 1),
                ):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        near_clear = True
                        break
                    if image.pixelColor(nx, ny).alpha() == 0:
                        near_clear = True
                        break
                if not near_clear:
                    continue
                if _is_magenta_bg(color, key, limit) or _is_pink_fringe(color):
                    image.setPixelColor(x, y, QColor(0, 0, 0, 0))
                    changed = True
                    continue
                cleaned = _despill_edge(color)
                if cleaned.alpha() != color.alpha() or cleaned.red() != color.red():
                    image.setPixelColor(x, y, cleaned)
                    changed = True
        if not changed:
            break

    # 去掉 cool/hype 顶边串进来的桌子底。
    _remove_orphan_top_strips(image)
    # 顶边残留木色碎点（未连成块的桌沿像素）。
    for y in range(min(14, height)):
        for x in range(width):
            color = image.pixelColor(x, y)
            if color.alpha() == 0:
                continue
            red, green, blue = color.red(), color.green(), color.blue()
            wood = (
                80 <= red <= 190
                and 40 <= green <= 130
                and blue <= green + 20
                and red >= blue + 20
            )
            if wood:
                image.setPixelColor(x, y, QColor(0, 0, 0, 0))
    return QPixmap.fromImage(image)


@dataclass(frozen=True)
class SpriteFrame:
    """
    单帧元数据。

    @author Kai
    @date 2026/08/05 17:19
    @description 保存原始帧图与切片矩形
    """

    pixmap: QPixmap
    source_rect: QRect


class PetAssets:
    """
    宠物动画帧资源管理。

    @author Kai
    @date 2026/08/06 09:54
    @description 优先加载 pet/frames/<mood>/ 预切片；否则从整图 16×8 切片
    """

    def __init__(self) -> None:
        self._sheet: Optional[QPixmap] = None
        self._frames: dict[str, list[SpriteFrame]] = {}

    def sheet(self) -> QPixmap:
        """
        读取 spritesheet 整图（预切片缺失时的回退源）。

        @return QPixmap；失败时为空图
        @author Kai
        @date 2026/08/06 09:54
        """
        if self._sheet is not None:
            return self._sheet
        self._sheet = QPixmap()
        for path in _asset_candidates():
            if path.exists() and self._sheet.load(str(path)):
                # 素材为 #FF00FF 色键底，加载后统一去背。
                self._sheet = make_sheet_background_transparent(self._sheet)
                return self._sheet
        return self._sheet

    def _load_sliced_frames(self, mood: str) -> list[SpriteFrame]:
        """
        从预切片目录加载一行动画帧。

        @param mood 状态 id
        @return 帧列表；目录不完整时返回空列表
        @author Kai
        @date 2026/08/06 09:54
        """
        folder = _mood_frame_dir(mood)
        if folder is None:
            return []
        frames: list[SpriteFrame] = []
        for column in range(SPRITE_COLUMNS):
            path = folder / f"{column:02d}.png"
            pix = QPixmap(str(path))
            if pix.isNull():
                return []
            frames.append(
                SpriteFrame(
                    pix,
                    QRect(0, 0, pix.width(), pix.height()),
                )
            )
        return frames

    def _load_sheet_frames(self, mood: str) -> list[SpriteFrame]:
        """
        从整图按 16×8 均匀网格切片。

        @param mood 状态 id
        @return 帧列表
        @author Kai
        @date 2026/08/06 09:54
        """
        key = mood if mood in MOOD_ROWS else MOOD_IDLE
        row = MOOD_ROWS.get(key, MOOD_ROWS[MOOD_IDLE])
        sheet = self.sheet()
        if sheet.isNull():
            return [
                SpriteFrame(
                    self._fallback_frame(),
                    QRect(0, 0, FALLBACK_SPRITE_SIZE, FALLBACK_SPRITE_SIZE),
                )
            ]
        cell_w = max(1, sheet.width() // SPRITE_COLUMNS)
        cell_h = max(1, sheet.height() // SPRITE_ROWS)
        frames: list[SpriteFrame] = []
        for column in range(SPRITE_COLUMNS):
            source = QRect(
                column * cell_w,
                row * cell_h,
                cell_w,
                cell_h,
            )
            frames.append(SpriteFrame(sheet.copy(source), source))
        return frames

    def frames_for_mood(self, mood: str) -> list[SpriteFrame]:
        """
        获取某个状态的一行动画帧（优先预切片）。

        @param mood 状态 id
        @return 该动作共 SPRITE_COLUMNS（16）帧
        @author Kai
        @date 2026/08/06 09:54
        """
        key = mood if mood in MOOD_ROWS else MOOD_IDLE
        if key in self._frames:
            return self._frames[key]
        frames = self._load_sliced_frames(key)
        if not frames:
            frames = self._load_sheet_frames(key)
        self._frames[key] = frames
        return frames

    def frame(self, mood: str, index: int) -> QPixmap:
        """
        获取当前动画帧。

        @param mood 状态 id
        @param index 帧序号
        @return QPixmap
        @author Kai
        @date 2026/08/05 17:19
        """
        frames = self.frames_for_mood(mood)
        if not frames:
            return self._fallback_frame()
        return frames[index % len(frames)].pixmap

    def frame_count(self, mood: str) -> int:
        """
        获取状态帧数。

        @param mood 状态 id
        @return 帧数
        @author Kai
        @date 2026/08/05 17:19
        """
        return max(1, len(self.frames_for_mood(mood)))

    def _fallback_frame(self) -> QPixmap:
        """
        spritesheet 缺失时的兜底像素块。

        @return fallback QPixmap
        @author Kai
        @date 2026/08/05 17:25
        """
        pix = QPixmap(FALLBACK_SPRITE_SIZE, FALLBACK_SPRITE_SIZE)
        pix.fill(QColor("#FDE68A"))
        painter = QPainter(pix)
        painter.setPen(QColor("#92400E"))
        painter.drawText(pix.rect(), 0x84, "犬")
        painter.end()
        return pix


class PetAnimationController(QObject):
    """
    宠物动画控制器。

    @author Kai
    @date 2026/08/05 17:19
    @description 管理当前状态、当前帧、播放速度，并用 QTimer 驱动
    """

    frame_changed = Signal()

    def __init__(self, assets: Optional[PetAssets] = None, parent=None) -> None:
        super().__init__(parent)
        self.assets = assets or PetAssets()
        self._mood = MOOD_IDLE
        self._frame_index = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.next_frame)
        self._timer.setInterval(MOOD_INTERVALS_MS[MOOD_IDLE])

    def set_mood(self, mood: str) -> None:
        """
        切换动画状态。

        @param mood 状态 id
        @author Kai
        @date 2026/08/05 17:19
        """
        next_mood = mood if mood in MOOD_ROWS else MOOD_IDLE
        if next_mood == self._mood:
            return
        self._mood = next_mood
        self._frame_index = 0
        self._timer.setInterval(MOOD_INTERVALS_MS.get(next_mood, 180))
        self.frame_changed.emit()

    def mood(self) -> str:
        """
        返回当前状态。

        @return mood id
        @author Kai
        @date 2026/08/05 17:19
        """
        return self._mood

    def frame_index(self) -> int:
        """
        返回当前帧序号。

        @return 帧序号
        @author Kai
        @date 2026/08/05 17:19
        """
        return self._frame_index

    def current_frame(self) -> QPixmap:
        """
        返回当前状态当前帧。

        @return QPixmap
        @author Kai
        @date 2026/08/05 17:19
        """
        return self.assets.frame(self._mood, self._frame_index)

    def start(self) -> None:
        """
        启动 QTimer 动画。

        @author Kai
        @date 2026/08/05 17:19
        """
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        """
        停止 QTimer 动画。

        @author Kai
        @date 2026/08/05 17:19
        """
        self._timer.stop()

    def next_frame(self) -> None:
        """
        推进一帧并通知 UI 重绘。

        @author Kai
        @date 2026/08/05 17:19
        """
        count = self.assets.frame_count(self._mood)
        self._frame_index = (self._frame_index + 1) % count
        self.frame_changed.emit()


class PetSpriteWidget(QWidget):
    """
    宠物 Sprite 绘制控件。

    @author Kai
    @date 2026/08/05 17:19
    @description 负责绘制当前 frame，可用于设置预览或详情卡扩展
    """

    def __init__(self, controller: Optional[PetAnimationController] = None, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller or PetAnimationController(pet_assets(), parent=self)
        self.controller.frame_changed.connect(self.update)
        self.controller.start()
        self.setMinimumSize(64, 64)

    def set_mood(self, mood: str) -> None:
        """
        切换显示状态。

        @param mood 状态 id
        @author Kai
        @date 2026/08/05 17:19
        """
        self.controller.set_mood(mood)

    def paintEvent(self, event) -> None:  # noqa: N802
        """
        绘制当前帧。

        @param event 绘制事件
        @author Kai
        @date 2026/08/05 17:19
        """
        _ = event
        painter = QPainter(self)
        paint_sprite_frame(
            painter,
            QRectF(0, 0, self.width(), self.height()),
            self.controller.current_frame(),
        )
        painter.end()


_ASSETS: Optional[PetAssets] = None
_CONTROLLER: Optional[PetAnimationController] = None


def pet_assets() -> PetAssets:
    """
    获取全局资源管理器。

    @return PetAssets
    @author Kai
    @date 2026/08/05 17:19
    """
    global _ASSETS
    if _ASSETS is None:
        _ASSETS = PetAssets()
    return _ASSETS


def pet_animation_controller(parent=None) -> PetAnimationController:
    """
    获取全局动画控制器。

    @param parent 可选 Qt parent
    @return PetAnimationController
    @author Kai
    @date 2026/08/05 17:19
    """
    global _CONTROLLER
    if _CONTROLLER is None:
        _CONTROLLER = PetAnimationController(pet_assets(), parent=parent)
    elif parent is not None and _CONTROLLER.parent() is None:
        _CONTROLLER.setParent(parent)
    return _CONTROLLER


def paint_sprite_frame(painter: QPainter, rect: QRectF, frame: QPixmap) -> None:
    """
    按目标区域绘制像素帧。

    @param painter 画笔
    @param rect 目标区域
    @param frame 当前帧
    @author Kai
    @date 2026/08/05 17:19
    """
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    if frame.isNull():
        painter.fillRect(rect, QColor("#FDE68A"))
    else:
        painter.drawPixmap(rect.toRect(), frame)
    painter.restore()


def paint_tray_pet(
    painter: QPainter,
    rect: QRectF,
    *,
    pet: str = PET_SHIBA,
    mood: str = MOOD_IDLE,
) -> None:
    """
    绘制当前宠物 sprite 帧。

    @param painter 画笔
    @param rect 区域
    @param pet 宠物 id（保留兼容参数，目前固定柴犬）
    @param mood 情绪 / 动作
    @author Kai
    @date 2026/08/05 17:19
    """
    _ = normalize_pet(pet)
    controller = pet_animation_controller()
    controller.set_mood(mood)
    paint_sprite_frame(painter, rect, controller.current_frame())


def make_pet_tray_icon(
    summary: AttendanceSummary,
    *,
    fallback_tone: str = "normal",
) -> QIcon:
    """
    生成带宠物的托盘图标；关闭宠物时回退到状态点。

    @param summary 摘要
    @param fallback_tone 回退 tone
    @return QIcon
    @author Kai
    @date 2026/08/05 17:19
    """
    from .icons import make_tray_icon

    if not getattr(S, "fun_enable", True) or not getattr(S, "fun_pet_enable", True):
        return make_tray_icon(0.0, fallback_tone)

    controller = pet_animation_controller()
    controller.set_mood(resolve_pet_mood(summary))
    icon = QIcon()
    for size in (16, 24, 32, 48, 64):
        pix = QPixmap(size, size)
        pix.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pix)
        paint_sprite_frame(
            painter,
            QRectF(0, 0, size, size),
            controller.current_frame(),
        )
        painter.end()
        icon.addPixmap(pix)
    return icon


def connect_pet_animation(
    repaint: Callable[[], None],
    *,
    parent=None,
) -> PetAnimationController:
    """
    连接动画帧刷新回调并启动 QTimer。

    @param repaint 每帧回调
    @param parent Qt parent
    @return PetAnimationController
    @author Kai
    @date 2026/08/05 17:19
    """
    controller = pet_animation_controller(parent=parent)
    try:
        controller.frame_changed.disconnect(repaint)
    except (RuntimeError, TypeError):
        pass
    controller.frame_changed.connect(repaint)
    controller.start()
    return controller
