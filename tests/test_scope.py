import unittest

from x_spider.scope import CrawlSpec, build_search_url, normalize_handle, normalize_handles, slug_text


class ScopeTests(unittest.TestCase):
    def test_normalize_handle_strips_at_sign_and_space(self) -> None:
        self.assertEqual(normalize_handle(" @authorA "), "authorA")

    def test_normalize_handles_deduplicates_and_sorts(self) -> None:
        self.assertEqual(normalize_handles(["@b", "a", "b"]), ["a", "b"])

    def test_slug_text_keeps_chinese_and_replaces_spaces(self) -> None:
        self.assertEqual(slug_text("青春 正好"), "青春_正好")

    def test_crawl_spec_scope_for_mentions(self) -> None:
        spec = CrawlSpec(
            task_type="search",
            media_type="images",
            mentions=("authorA", "authorB"),
            keyword="青春正好",
        )
        self.assertEqual(spec.scope_type, "mentions")
        self.assertEqual(spec.scope_name, "authorA_authorB")
        self.assertEqual(
            spec.scope_key,
            "type=search|publishers=-|mentions=authorA,authorB|keyword=青春正好|media=images",
        )

    def test_build_search_url_uses_expected_query_parts(self) -> None:
        spec = CrawlSpec(
            task_type="search",
            media_type="images",
            publishers=("authorA",),
            mentions=("authorB",),
            keyword="苹果",
        )
        url = build_search_url(spec)
        self.assertTrue(url.startswith("https://x.com/search?"))
        self.assertIn("from%3AauthorA", url)
        self.assertIn("%40authorB", url)
        self.assertIn("%E8%8B%B9%E6%9E%9C", url)
        self.assertIn("filter%3Aimages", url)


if __name__ == "__main__":
    unittest.main()
