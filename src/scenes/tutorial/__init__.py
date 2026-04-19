"""
Tutorial scene — 오너 첫 접속부터 첫 친구 생성까지.

모듈 import만으로 scene 레지스트리에 등록된다.
외부(profile.py, supervisors.py 등)는 src.scenes API만 써도 되지만
직접 scene 인스턴스 가져오려면 `from src.scenes.tutorial import scene`.
"""
from src.scenes.tutorial.scene import scene

__all__ = ["scene"]
