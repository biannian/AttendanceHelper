# Copyright (c) iGroup China.
# All rights reserved.
"""
将 dog16-v3.png 按 16×8 网格切片并色键去背。

@author Kai
@date 2026/08/06 09:54
@description 输出 pet/frames/<mood>/00.png … 15.png，供托盘宠物播放
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication

# 与 tray_pet 保持一致。
ROW_MOODS = [
    "yawn",
    "type",
    "stretch",
    "watch",
    "pack",
    "cool",
    "wave",
    "hype",
]
COLS = 16
ROWS = 8


def chroma_cell(image: QImage) -> QImage:
    """
    对单帧做洋红边缘 flood-fill 去背。

    @param image 原始帧
    @return 透明背景帧
    @author Kai
    @date 2026/08/06 09:54
    """
    # 复用运行时同一套色键逻辑，避免脚本与托盘行为不一致。
    from attendance_helper.tray_pet import make_sheet_background_transparent

    pix = make_sheet_background_transparent(QPixmap.fromImage(image))
    return pix.toImage()


def slice_sheet(src: Path, out_root: Path) -> int:
    """
    将整图切成 16×8 独立 PNG。

    @param src 源 spritesheet
    @param out_root frames 输出根目录
    @return 写出帧数
    @author Kai
    @date 2026/08/06 09:54
    """
    sheet = QImage(str(src))
    if sheet.isNull():
        raise FileNotFoundError(f"无法读取: {src}")
    cell_w = sheet.width() // COLS
    cell_h = sheet.height() // ROWS
    count = 0
    for row, mood in enumerate(ROW_MOODS):
        folder = out_root / mood
        folder.mkdir(parents=True, exist_ok=True)
        for col in range(COLS):
            cell = sheet.copy(col * cell_w, row * cell_h, cell_w, cell_h)
            cell = chroma_cell(cell)
            path = folder / f"{col:02d}.png"
            if not cell.save(str(path), "PNG"):
                raise OSError(f"保存失败: {path}")
            count += 1
        print(f"row {row} {mood} -> {folder}")
    return count


def main() -> int:
    """
    命令行入口。

    @return 进程退出码
    @author Kai
    @date 2026/08/06 09:54
    """
    _ = QApplication(sys.argv)
    # 保证可从 windows/ 工作目录导入 attendance_helper。
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    pet_dir = Path(__file__).resolve().parent
    src = pet_dir / "dog16-v3.png"
    out_root = pet_dir / "frames"
    saved = slice_sheet(src, out_root)
    print(f"saved {saved} frames to {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
