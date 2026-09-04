import unittest

from java_block_diff import JavaBlockSequenceMatcher


def L(text):
    return [line + "\n" for line in text.strip("\n").split("\n")]


class TestJavaBlockSequenceMatcher(unittest.TestCase):
    def test_plain_lines_behave_like_difflib(self):
        a = L("aaa\nbbb\nccc")
        b = L("aaa\nxxx\nccc")
        sm = JavaBlockSequenceMatcher(None, a, b)
        ops = sm.get_opcodes()
        self.assertEqual(
            ops,
            [
                ("equal", 0, 1, 0, 1),
                ("replace", 1, 2, 1, 2),
                ("equal", 2, 3, 2, 3),
            ],
        )

    def test_block_treated_as_single_unit(self):
        a = L(
            """
before
// ADD START
line1
line2
// ADD END
after
"""
        )
        b = L(
            """
before
// ADD START
line1
line2changed
// ADD END
after
"""
        )
        sm = JavaBlockSequenceMatcher(None, a, b)
        ops = sm.get_opcodes()
        # ブロック内の1行だけ変わっても、ブロック全体(4行)が1つのreplaceになる
        self.assertEqual(
            ops,
            [
                ("equal", 0, 1, 0, 1),
                ("replace", 1, 5, 1, 5),
                ("equal", 5, 6, 5, 6),
            ],
        )

    def test_block_unchanged_is_equal(self):
        a = L(
            """
// ADD START
line1
// ADD END
"""
        )
        b = L(
            """
// ADD START
line1
// ADD END
"""
        )
        sm = JavaBlockSequenceMatcher(None, a, b)
        ops = sm.get_opcodes()
        self.assertEqual(ops, [("equal", 0, 3, 0, 3)])

    def test_ratio_matches_difflib_semantics(self):
        a = L("aaa\nbbb")
        b = L("aaa\nbbb")
        sm = JavaBlockSequenceMatcher(None, a, b)
        self.assertEqual(sm.ratio(), 1.0)

    def test_custom_markers(self):
        a = L(
            """
x
/* GEN-BEGIN */
foo
/* GEN-END */
y
"""
        )
        b = L(
            """
x
/* GEN-BEGIN */
bar
/* GEN-END */
y
"""
        )
        sm = JavaBlockSequenceMatcher(
            None, a, b, block_start=r"/\*\s*GEN-BEGIN", block_end=r"/\*\s*GEN-END"
        )
        ops = sm.get_opcodes()
        self.assertEqual(
            ops,
            [
                ("equal", 0, 1, 0, 1),
                ("replace", 1, 4, 1, 4),
                ("equal", 4, 5, 4, 5),
            ],
        )

    def test_get_matching_blocks_line_indices(self):
        a = L("aaa\nbbb\nccc")
        b = L("aaa\nxxx\nccc")
        sm = JavaBlockSequenceMatcher(None, a, b)
        blocks = sm.get_matching_blocks()
        self.assertEqual(blocks[0], (0, 0, 1))
        self.assertEqual(blocks[-1], (3, 3, 0))


if __name__ == "__main__":
    unittest.main()
