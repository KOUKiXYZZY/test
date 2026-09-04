import unittest

from java_block_diff import (
    BlockMarkerError,
    JavaBlockSequenceMatcher,
    PlainSequenceMatcher,
    parse_blocks,
)


def L(text):
    return [line + "\n" for line in text.strip("\n").split("\n")]


class TestPlainSequenceMatcher(unittest.TestCase):
    def test_plain_lines_behave_like_difflib(self):
        a = L("aaa\nbbb\nccc")
        b = L("aaa\nxxx\nccc")
        sm = PlainSequenceMatcher(None, a, b)
        self.assertEqual(
            sm.get_opcodes(),
            [
                ("equal", 0, 1, 0, 1),
                ("replace", 1, 2, 1, 2),
                ("equal", 2, 3, 2, 3),
            ],
        )

    def test_ratio(self):
        a = L("aaa\nbbb")
        b = L("aaa\nbbb")
        self.assertEqual(PlainSequenceMatcher(None, a, b).ratio(), 1.0)


class TestParseBlocks(unittest.TestCase):
    def test_add_block(self):
        lines = L(
            """
before
// ADD開始 <NGY-001>
line1
line2
// ADD終了 <NGY-001>
after
"""
        )
        blocks = parse_blocks(lines)
        self.assertEqual(len(blocks), 1)
        blk = blocks[0]
        self.assertEqual(blk.block_type, "ADD")
        self.assertEqual(blk.ngy_id, "NGY-001")
        self.assertEqual(blk.before_lines, [])
        self.assertEqual(blk.after_lines, L("line1\nline2"))

    def test_mod_block_splits_before_after(self):
        lines = L(
            """
// MOD開始 <NGY-010>
// int x = 1;
int x = 2;
// MOD終了 <NGY-010>
"""
        )
        blocks = parse_blocks(lines)
        blk = blocks[0]
        self.assertEqual(blk.block_type, "MOD")
        self.assertEqual(blk.before_lines, ["int x = 1;\n"])
        self.assertEqual(blk.after_lines, ["int x = 2;\n"])

    def test_del_block_all_commented(self):
        lines = L(
            """
// DEL開始 <NGY-020>
// int unused = 0;
// DEL終了 <NGY-020>
"""
        )
        blocks = parse_blocks(lines)
        blk = blocks[0]
        self.assertEqual(blk.block_type, "DEL")
        self.assertEqual(blk.before_lines, ["int unused = 0;\n"])
        self.assertEqual(blk.after_lines, [])

    def test_unmatched_end_raises(self):
        lines = L(
            """
// ADD終了 <NGY-999>
"""
        )
        with self.assertRaises(BlockMarkerError):
            parse_blocks(lines)

    def test_unclosed_start_raises(self):
        lines = L(
            """
// ADD開始 <NGY-001>
line1
"""
        )
        with self.assertRaises(BlockMarkerError):
            parse_blocks(lines)

    def test_mismatched_type_raises(self):
        lines = L(
            """
// MOD開始 <NGY-001>
// old
new
// DEL終了 <NGY-001>
"""
        )
        with self.assertRaises(BlockMarkerError):
            parse_blocks(lines)

    def test_mismatched_id_raises(self):
        lines = L(
            """
// ADD開始 <NGY-001>
line1
// ADD終了 <NGY-002>
"""
        )
        with self.assertRaises(BlockMarkerError):
            parse_blocks(lines)

    def test_nested_blocks_outer_only(self):
        lines = L(
            """
// MOD開始 <NGY-100>
// outer old
// ADD開始 <NGY-101>
inner new
// ADD終了 <NGY-101>
// MOD終了 <NGY-100>
"""
        )
        blocks = parse_blocks(lines)
        # 一番外側のブロックだけが top-level として返る
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].block_type, "MOD")
        self.assertEqual(blocks[0].ngy_id, "NGY-100")


class TestJavaBlockSequenceMatcher(unittest.TestCase):
    def test_no_markers_behaves_like_plain_diff(self):
        a = L("aaa\nbbb\nccc")
        b = L("aaa\nxxx\nccc")
        sm = JavaBlockSequenceMatcher(None, a, b)
        self.assertEqual(
            sm.get_opcodes(),
            [
                ("equal", 0, 1, 0, 1),
                ("replace", 1, 2, 1, 2),
                ("equal", 2, 3, 2, 3),
            ],
        )

    def test_add_block_is_insert(self):
        a = L("before\nafter")
        b = L(
            """
before
// ADD開始 <NGY-001>
new1
new2
// ADD終了 <NGY-001>
after
"""
        )
        sm = JavaBlockSequenceMatcher(None, a, b)
        ops = sm.get_opcodes()
        self.assertIn(("equal", 0, 1, 0, 1), ops)
        self.assertIn(("insert", 1, 1, 1, 5), ops)
        self.assertIn(("equal", 1, 2, 5, 6), ops)

        anns = sm.get_block_annotations()
        self.assertEqual(len(anns), 1)
        self.assertEqual(anns[0]["block_type"], "ADD")
        self.assertEqual(anns[0]["ngy_id"], "NGY-001")
        self.assertEqual(anns[0]["a_range"], (1, 1))

    def test_mod_block_maps_to_original_code(self):
        a = L("before\nint x = 1;\nafter")
        b = L(
            """
before
// MOD開始 <NGY-010>
// int x = 1;
int x = 2;
// MOD終了 <NGY-010>
after
"""
        )
        sm = JavaBlockSequenceMatcher(None, a, b)
        ops = sm.get_opcodes()
        # 変更前の "int x = 1;" (a側1行目)がブロックに対応付けられ replace になる
        self.assertIn(("replace", 1, 2, 1, 5), ops)

        anns = sm.get_block_annotations()
        self.assertEqual(anns[0]["block_type"], "MOD")
        self.assertTrue(anns[0]["matched"])
        self.assertEqual(anns[0]["a_range"], (1, 2))

    def test_del_block_maps_to_original_code(self):
        a = L("before\nint unused = 0;\nafter")
        b = L(
            """
before
// DEL開始 <NGY-020>
// int unused = 0;
// DEL終了 <NGY-020>
after
"""
        )
        sm = JavaBlockSequenceMatcher(None, a, b)
        ops = sm.get_opcodes()
        self.assertIn(("delete", 1, 2, 1, 4), ops)

        anns = sm.get_block_annotations()
        self.assertEqual(anns[0]["block_type"], "DEL")
        self.assertTrue(anns[0]["matched"])

    def test_unmatched_marker_raises(self):
        a = L("x")
        b = L(
            """
// ADD開始 <NGY-001>
line1
"""
        )
        with self.assertRaises(BlockMarkerError):
            JavaBlockSequenceMatcher(None, a, b)

    def test_add_without_original_code_is_fine(self):
        # ADDは新規追加なので、左側に対応するコードが無くてもエラーにならない
        a = L("before\nafter")
        b = L(
            """
before
// ADD開始 <NGY-001>
new1
// ADD終了 <NGY-001>
after
"""
        )
        sm = JavaBlockSequenceMatcher(None, a, b)  # 例外が出なければOK
        self.assertTrue(sm.get_block_annotations()[0]["matched"])

    def test_mod_without_matching_original_code_is_not_an_error(self):
        # 例外的に対応する変更前コードが見つからないケースもあるため、
        # エラーにはせず matched=False として扱う
        a = L("before\nsomething else\nafter")
        b = L(
            """
before
// MOD開始 <NGY-010>
// int x = 1;
int x = 2;
// MOD終了 <NGY-010>
after
"""
        )
        sm = JavaBlockSequenceMatcher(None, a, b)
        self.assertFalse(sm.get_block_annotations()[0]["matched"])

    def test_del_without_matching_original_code_is_not_an_error(self):
        a = L("before\nsomething else\nafter")
        b = L(
            """
before
// DEL開始 <NGY-020>
// int unused = 0;
// DEL終了 <NGY-020>
after
"""
        )
        sm = JavaBlockSequenceMatcher(None, a, b)
        self.assertFalse(sm.get_block_annotations()[0]["matched"])

    def test_ratio_still_works(self):
        a = L("aaa\nbbb")
        b = L("aaa\nbbb")
        self.assertEqual(JavaBlockSequenceMatcher(None, a, b).ratio(), 1.0)


if __name__ == "__main__":
    unittest.main()
