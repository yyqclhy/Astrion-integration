"""按钮实体暴露范围测试。"""
import ast
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "my_ir"


class ButtonExposureTests(unittest.TestCase):
    """确保 Integration 不再暴露蓝牙取消配对按钮。"""

    def test_bluetooth_unpair_button_is_not_exposed(self):
        tree = ast.parse((COMPONENT / "button.py").read_text(encoding="utf-8-sig"))
        class_names = {
            node.name for node in tree.body if isinstance(node, ast.ClassDef)
        }
        self.assertNotIn("BluetoothUnpairButton", class_names)

        for relative_path in (
            "strings.json", "translations/en.json", "translations/zh-Hans.json"
        ):
            content = json.loads((COMPONENT / relative_path).read_text(encoding="utf-8-sig"))
            self.assertNotIn("unpair", content["entity"]["button"])


if __name__ == "__main__":
    unittest.main()
