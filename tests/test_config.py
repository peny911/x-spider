import os
import tempfile
import unittest
import importlib.util
from pathlib import Path

if importlib.util.find_spec("pydantic_settings") is None:
    raise unittest.SkipTest("pydantic_settings is not installed")

from x_spider.config import find_env_file, load_project_env, parse_env_value


class ConfigTests(unittest.TestCase):
    def test_find_env_file_searches_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "a" / "b"
            nested.mkdir(parents=True)
            env_path = root / ".env"
            env_path.write_text("X_SPIDER_HEADLESS=true\n", encoding="utf-8")

            self.assertEqual(find_env_file(nested), env_path)

    def test_parse_env_value_handles_quotes_and_comments(self) -> None:
        self.assertEqual(parse_env_value('"hello world"'), "hello world")
        self.assertEqual(parse_env_value("true # comment"), "true")
        self.assertEqual(parse_env_value(""), "")

    def test_load_project_env_overrides_existing_x_spider_env(self) -> None:
        original = os.environ.get("X_SPIDER_HEADLESS")
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.environ["X_SPIDER_HEADLESS"] = "true"
                Path(tmp, ".env").write_text("X_SPIDER_HEADLESS=false\n", encoding="utf-8")
                os.chdir(tmp)

                load_project_env()

                self.assertEqual(os.environ["X_SPIDER_HEADLESS"], "false")
            finally:
                os.chdir(previous_cwd)
                if original is None:
                    os.environ.pop("X_SPIDER_HEADLESS", None)
                else:
                    os.environ["X_SPIDER_HEADLESS"] = original


if __name__ == "__main__":
    unittest.main()
