"""宠物模型管理模块

支持多套宠物外观（模型）的切换管理。
每个模型是 assets/models/<模型名>/ 下的一个子目录，包含：
    pet.jpg/png       — 默认显示图（必需）
    thumbs_up.gif     — 鼓励动画
    yawn.gif          — 打哈欠
    sleep.gif         — 睡觉
    wave.gif          — 挥手
    think.gif         — 思考
    happy.gif         — 开心
    confused.gif      — 困惑

Assets 根目录中的图片作为默认 fallback。
"""

import glob
from pathlib import Path
from typing import List, Optional


class PetModelManager:
    """宠物模型管理器"""

    MODELS_DIR = Path(__file__).parent / "assets" / "models"

    # 每套模型应包含的文件（pet.jpg/png 为必需）
    MODEL_FILES = ["pet.png", "pet.jpg"]
    ANIM_FILES = [
        "thumbs_up.gif", "yawn.gif", "sleep.gif", "wave.gif",
        "think.gif", "happy.gif", "confused.gif",
    ]

    def __init__(self):
        self._current_model = ""  # "" 表示使用根 assets/

    # ----- 模型发现 -----

    def get_available_models(self) -> List[dict]:
        """
        扫描 models 目录，返回可用模型列表

        Returns:
            [{"id": "cat", "name": "猫猫", "has_preview": True}, ...]
        """
        models_dir = self.MODELS_DIR
        if not models_dir.exists():
            return []

        models = []
        for subdir in sorted(models_dir.iterdir()):
            if not subdir.is_dir():
                continue
            model_id = subdir.name
            # 检查是否有 pet 图片（有效模型）
            has_pet = any((subdir / f).exists() for f in self.MODEL_FILES)
            if not has_pet:
                continue
            models.append({
                "id": model_id,
                "name": model_id,  # 可自定义中文名
                "path": str(subdir),
            })
        return models

    # ----- 路径解析 -----

    def get_asset_dir(self, model_name: str = None) -> Path:
        """获取模型的资源目录"""
        if model_name:
            model_path = self.MODELS_DIR / model_name
            if model_path.exists():
                return model_path
        # fallback 到根 assets
        return Path(__file__).parent / "assets"

    def find_image(self, model_name: str, *names: str) -> Optional[str]:
        """
        在模型中查找图片文件

        Args:
            model_name: 模型名，None 表示当前模型
            *names: 要查找的文件名列表

        Returns:
            第一个找到的文件的路径，或 None
        """
        asset_dir = self.get_asset_dir(model_name)
        for name in names:
            path = asset_dir / name
            if path.exists():
                return str(path)
        return None

    def find_default_image(self, model_name: str = None) -> Optional[str]:
        """查找模型的默认宠物图"""
        return self.find_image(model_name, "pet.png", "pet.jpg", "pet.gif")

    def find_anim_files(self, model_name: str = None) -> List[tuple]:
        """
        查找模型中所有动画文件

        Returns:
            [(动画名, 文件路径), ...]
        """
        asset_dir = self.get_asset_dir(model_name)
        if not asset_dir.exists():
            return []

        results = []
        for pattern in ("*.gif", "*.png"):
            for f in sorted(asset_dir.glob(pattern)):
                name = f.stem
                if name != "pet":  # pet 是默认图，不是动画
                    results.append((name, str(f)))
        return results

    # ----- 当前模型管理 -----

    @property
    def current_model(self) -> str:
        return self._current_model

    @current_model.setter
    def current_model(self, model_id: str):
        self._current_model = model_id or ""

    def get_current_asset_dir(self) -> Path:
        """获取当前模型的资源目录"""
        return self.get_asset_dir(self._current_model)

    def get_current_default_image(self) -> Optional[str]:
        """获取当前模型的默认图"""
        return self.find_default_image(self._current_model)


# 全局实例
model_manager = PetModelManager()
