#!/usr/bin/env python3
"""java_block_diff.py

Java向けのブロック単位diffツール。

difflib.SequenceMatcher と同じインタフェース(get_opcodes / get_matching_blocks /
ratio など)を提供しつつ、

    // ADD START
    ...
    // ADD END

のようなコメントペアで囲まれた範囲を「1ブロック」としてまとめて差分判定する。
ブロックの外側は通常のdifflibと同じ行単位の差分になる。

使い方は difflib.SequenceMatcher とほぼ同じ:

    >>> sm = JavaBlockSequenceMatcher(None, left_lines, right_lines)
    >>> for tag, i1, i2, j1, j2 in sm.get_opcodes():
    ...     ...

get_opcodes() / get_matching_blocks() は「ブロック単位」ではなく、常に
元の行番号(1行単位のインデックス)ベースで結果を返す。ブロックとして
まとめられた範囲は、ブロック内のどこか1行でも差があれば
ブロック全体が replace/insert/delete としてまとまって出力される。
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from typing import Callable, List, Optional, Sequence, Tuple

Opcode = Tuple[str, int, int, int, int]
MatchingBlock = Tuple[int, int, int]

DEFAULT_BLOCK_START = r"//\s*ADD\s*START"
DEFAULT_BLOCK_END = r"//\s*ADD\s*END"


class _Unit:
    """SequenceMatcher に渡す1要素。通常行 or ブロックをラップする。"""

    __slots__ = ("start", "end", "key")

    def __init__(self, start: int, end: int, key: str):
        # [start, end) は元の行配列における半開区間。
        # 通常行の場合は end == start + 1。
        self.start = start
        self.end = end
        self.key = key

    def __eq__(self, other):
        return isinstance(other, _Unit) and self.key == other.key

    def __hash__(self):
        return hash(self.key)


def _group_units(
    lines: Sequence[str],
    block_start: "re.Pattern",
    block_end: "re.Pattern",
) -> List[_Unit]:
    """行配列を走査し、ブロックコメントで囲まれた範囲を1つの _Unit にまとめる。

    ネストは考慮しない(Javaのコメントブロックはフラットである前提)。
    START に対応する END が見つからない場合は、そのSTART行以降を
    ファイル末尾までのブロックとして扱う。
    """
    units: List[_Unit] = []
    i = 0
    n = len(lines)
    while i < n:
        if block_start.search(lines[i]):
            j = i + 1
            while j < n and not block_end.search(lines[j]):
                j += 1
            end = min(j + 1, n) if j < n else n
            key = "".join(lines[i:end])
            units.append(_Unit(i, end, key))
            i = end
        else:
            units.append(_Unit(i, i + 1, lines[i]))
            i += 1
    return units


class JavaBlockSequenceMatcher:
    """difflib.SequenceMatcher と互換のインタフェースを持つブロック単位diffクラス。

    a は互換性のため受け取るが使用しない(difflib.SequenceMatcher(isjunk, a, b) 互換)。
    """

    def __init__(
        self,
        isjunk: Optional[Callable[[str], bool]] = None,
        a: Sequence[str] = "",
        b: Sequence[str] = "",
        autojunk: bool = True,
        block_start: str = DEFAULT_BLOCK_START,
        block_end: str = DEFAULT_BLOCK_END,
    ):
        self.a = list(a)
        self.b = list(b)
        self._block_start_re = re.compile(block_start)
        self._block_end_re = re.compile(block_end)
        self._units_a = _group_units(self.a, self._block_start_re, self._block_end_re)
        self._units_b = _group_units(self.b, self._block_start_re, self._block_end_re)
        self._sm = difflib.SequenceMatcher(
            isjunk, self._units_a, self._units_b, autojunk=autojunk
        )

    def set_seqs(self, a: Sequence[str], b: Sequence[str]) -> None:
        self.a = list(a)
        self.b = list(b)
        self._units_a = _group_units(self.a, self._block_start_re, self._block_end_re)
        self._units_b = _group_units(self.b, self._block_start_re, self._block_end_re)
        self._sm.set_seqs(self._units_a, self._units_b)

    def get_opcodes(self) -> List[Opcode]:
        opcodes: List[Opcode] = []
        for tag, ui1, ui2, uj1, uj2 in self._sm.get_opcodes():
            i1 = self._units_a[ui1].start if ui1 < len(self._units_a) else len(self.a)
            i2 = self._units_a[ui2 - 1].end if ui2 > ui1 else i1
            j1 = self._units_b[uj1].start if uj1 < len(self._units_b) else len(self.b)
            j2 = self._units_b[uj2 - 1].end if uj2 > uj1 else j1
            opcodes.append((tag, i1, i2, j1, j2))
        return opcodes

    def get_matching_blocks(self) -> List[MatchingBlock]:
        blocks: List[MatchingBlock] = []
        for ui, uj, size in self._sm.get_matching_blocks():
            if size == 0:
                blocks.append((len(self.a), len(self.b), 0))
                continue
            i = self._units_a[ui].start
            j = self._units_b[uj].start
            length = self._units_a[ui + size - 1].end - i
            blocks.append((i, j, length))
        return blocks

    def ratio(self) -> float:
        return self._sm.ratio()

    def quick_ratio(self) -> float:
        return self._sm.quick_ratio()

    def real_quick_ratio(self) -> float:
        return self._sm.real_quick_ratio()


def java_block_diff(
    a: Sequence[str],
    b: Sequence[str],
    block_start: str = DEFAULT_BLOCK_START,
    block_end: str = DEFAULT_BLOCK_END,
    lineterm: str = "\n",
    fromfile: str = "",
    tofile: str = "",
) -> List[str]:
    """difflib.unified_diff 相当の出力を、ブロック単位で生成するヘルパー。"""
    sm = JavaBlockSequenceMatcher(None, a, b, block_start=block_start, block_end=block_end)
    out: List[str] = []
    if fromfile or tofile:
        out.append(f"--- {fromfile}{lineterm}")
        out.append(f"+++ {tofile}{lineterm}")
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for line in a[i1:i2]:
                out.append(" " + line)
        else:
            if tag in ("delete", "replace"):
                for line in a[i1:i2]:
                    out.append("-" + line)
            if tag in ("insert", "replace"):
                for line in b[j1:j2]:
                    out.append("+" + line)
    return out


def read_lines(path: str, encoding: str) -> List[str]:
    with open(path, "r", encoding=encoding, newline="") as f:
        return f.readlines()


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Javaのブロック(ADD START/ENDなど)単位でdiffを出すツール"
    )
    p.add_argument("left")
    p.add_argument("right")
    p.add_argument("--block-start", default=DEFAULT_BLOCK_START, help="ブロック開始コメントの正規表現")
    p.add_argument("--block-end", default=DEFAULT_BLOCK_END, help="ブロック終了コメントの正規表現")
    p.add_argument("--encoding", default="utf-8")
    p.add_argument("-o", "--output", default=None)
    args = p.parse_args(argv)

    left_lines = read_lines(args.left, args.encoding)
    right_lines = read_lines(args.right, args.encoding)

    diff_lines = java_block_diff(
        left_lines,
        right_lines,
        block_start=args.block_start,
        block_end=args.block_end,
        fromfile=args.left,
        tofile=args.right,
    )

    if args.output:
        with open(args.output, "w", encoding=args.encoding, newline="") as f:
            f.writelines(diff_lines)
    else:
        sys.stdout.writelines(diff_lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
