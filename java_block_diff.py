#!/usr/bin/env python3
"""java_block_diff.py

Java向けのブロック単位diffツール。

difflib.SequenceMatcher と同じインタフェース(get_opcodes / get_matching_blocks /
ratio など)を提供しつつ、以下のマーカーで囲まれたブロックを1つの変更単位として
扱い、変更前(left / a)のコードと対応付けて差分を出す。

    // ADD開始 <NGY-xxx>
    ...新規コード...
    // ADD終了 <NGY-xxx>

    // MOD開始 <NGY-xxx>
    // 元のコード(コメント化されている)
    新しいコード
    // MOD終了 <NGY-xxx>

    // DEL開始 <NGY-xxx>
    // 削除されたコード(コメント化されている)
    // DEL終了 <NGY-xxx>

- 開始マーカーと終了マーカーは種別(ADD/MOD/DEL)とNGY-IDが一致していなければ
  ならない。対応するペアが見つからない場合は BlockMarkerError を送出する。
- ブロックは入れ子になってよい。入れ子になった場合、一番外側のブロックを
  1つの変更単位として扱い、差分はその外側ブロック単位でまとめて出す。
- MOD/DEL ブロック内の「// 」で始まる行は "変更前のコード" とみなし、
  先頭の "// " を取り除いた上で、変更前(left)ファイルの該当箇所を
  そのままの並びで探索してマッチングする。マッチした範囲が
  「このブロックに対応する変更前コード」として opcode の a 側範囲になる。
  それ以外の行(コメントでない行)は "変更後のコード" とみなす。
- ADD ブロックには変更前コードが存在しないため、常に insert として扱われる。

NOTE: difflib は使用禁止のため、通常区間(ブロックの外側)の差分は
自前実装のLCS(動的計画法による最長共通部分列)で計算している。
"""
from __future__ import annotations

import argparse
import re
import sys
from typing import List, Optional, Sequence, Tuple

Opcode = Tuple[str, int, int, int, int]
MatchingBlock = Tuple[int, int, int]

BLOCK_TYPES = ("ADD", "MOD", "DEL")

_START_RE = re.compile(r"//\s*(ADD|MOD|DEL)開始\s*<(NGY-[^>\s]+)>")
_END_RE = re.compile(r"//\s*(ADD|MOD|DEL)終了\s*<(NGY-[^>\s]+)>")
_COMMENT_LINE_RE = re.compile(r"^\s*//\s?(.*)$")


class BlockMarkerError(ValueError):
    """ADD/MOD/DEL マーカーの開始・終了ペアが不正なときに送出される例外。"""


class Block:
    """1つの ADD/MOD/DEL ブロック(一番外側のもの)を表す。"""

    __slots__ = ("block_type", "ngy_id", "start", "end", "before_lines", "after_lines")

    def __init__(
        self,
        block_type: str,
        ngy_id: str,
        start: int,
        end: int,
        before_lines: List[str],
        after_lines: List[str],
    ):
        self.block_type = block_type
        self.ngy_id = ngy_id
        # [start, end) はブロックが属するファイル(b側)における行範囲(マーカー行を含む)
        self.start = start
        self.end = end
        self.before_lines = before_lines
        self.after_lines = after_lines

    def __repr__(self):
        return (
            f"Block({self.block_type}, {self.ngy_id!r}, "
            f"start={self.start}, end={self.end})"
        )


def _strip_comment_prefix(line: str) -> str:
    has_nl = line.endswith("\n")
    body = line[:-1] if has_nl else line
    m = _COMMENT_LINE_RE.match(body)
    content = m.group(1) if m else body
    return content + ("\n" if has_nl else "")


def _split_before_after(content_lines: List[str], block_type: str) -> Tuple[List[str], List[str]]:
    if block_type == "ADD":
        return [], list(content_lines)
    if block_type == "DEL":
        before = [_strip_comment_prefix(line) for line in content_lines]
        return before, []
    # MOD: "//" で始まる行が変更前、それ以外が変更後
    before: List[str] = []
    after: List[str] = []
    for line in content_lines:
        if re.match(r"^\s*//", line):
            before.append(_strip_comment_prefix(line))
        else:
            after.append(line)
    return before, after


def parse_blocks(lines: Sequence[str]) -> List[Block]:
    """ADD/MOD/DEL マーカーを走査し、一番外側のブロック一覧を返す。

    入れ子は許容するが、開始・終了マーカーは種別とNGY-IDが一致した状態で
    正しくペアになっている必要がある。ペアが崩れている場合は
    BlockMarkerError を送出する。
    """
    stack: List[dict] = []
    top_level: List[Block] = []

    for idx, line in enumerate(lines):
        start_m = _START_RE.search(line)
        end_m = _END_RE.search(line)

        if start_m:
            btype, ngy_id = start_m.group(1), start_m.group(2)
            stack.append({"type": btype, "id": ngy_id, "start": idx, "content": []})
            continue

        if end_m:
            btype, ngy_id = end_m.group(1), end_m.group(2)
            if not stack:
                raise BlockMarkerError(
                    f"対応する開始マーカーのない終了マーカーです: "
                    f"{btype}終了 <{ngy_id}> ({idx + 1}行目)"
                )
            top = stack[-1]
            if top["type"] != btype or top["id"] != ngy_id:
                raise BlockMarkerError(
                    f"マーカーが対応していません: "
                    f"開始={top['type']}開始 <{top['id']}> ({top['start'] + 1}行目) に対し "
                    f"終了={btype}終了 <{ngy_id}> ({idx + 1}行目)"
                )
            closed = stack.pop()
            if stack:
                # 入れ子ブロックが閉じた場合、そのブロック全体を親の内容として引き継ぐ
                stack[-1]["content"].extend(lines[closed["start"]: idx + 1])
            else:
                before, after = _split_before_after(closed["content"], btype)
                top_level.append(Block(btype, ngy_id, closed["start"], idx + 1, before, after))
            continue

        if stack:
            stack[-1]["content"].append(line)

    if stack:
        unclosed = stack[-1]
        raise BlockMarkerError(
            f"閉じられていないブロックがあります: "
            f"{unclosed['type']}開始 <{unclosed['id']}> ({unclosed['start'] + 1}行目)"
        )

    return top_level


def _find_subsequence(a: Sequence[str], sub: Sequence[str], start: int) -> Optional[int]:
    """a[start:] の中から sub と完全一致する連続部分列の開始位置を探す。"""
    if not sub:
        return start
    n, m = len(a), len(sub)
    for i in range(start, n - m + 1):
        if a[i:i + m] == list(sub):
            return i
    return None


def _lcs_opcodes(a: Sequence[str], b: Sequence[str]) -> List[Opcode]:
    """difflib非依存のLCSベース行diff(動的計画法)。"""
    n, m = len(a), len(b)
    if n == 0 and m == 0:
        return []

    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        row, row_next, ai = dp[i], dp[i + 1], a[i]
        for j in range(m - 1, -1, -1):
            if ai == b[j]:
                row[j] = row_next[j + 1] + 1
            else:
                row[j] = row[j + 1] if row[j + 1] >= row_next[j] else row_next[j]

    blocks: List[Tuple[int, int, int]] = []
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            si, sj = i, j
            while i < n and j < m and a[i] == b[j]:
                i += 1
                j += 1
            blocks.append((si, sj, i - si))
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    blocks.append((n, m, 0))

    opcodes: List[Opcode] = []
    i = j = 0
    for ai, bj, size in blocks:
        tag = ""
        if i < ai and j < bj:
            tag = "replace"
        elif i < ai:
            tag = "delete"
        elif j < bj:
            tag = "insert"
        if tag:
            opcodes.append((tag, i, ai, j, bj))
        i, j = ai + size, bj + size
        if size:
            opcodes.append(("equal", ai, i, bj, j))
    return opcodes


def _diff_with_blocks(
    a: Sequence[str], b: Sequence[str], blocks: List[Block]
) -> Tuple[List[Opcode], List[dict]]:
    """ブロックを変更前(a)コードと対応付けながら全体のopcodesを組み立てる。

    2段階で処理する:
      1. before_lines を持つブロック(MOD/DEL)について、a側での対応位置
         (アンカー)を先読みで確定させる。
      2. アンカーを境界として、ブロックとブロックの間(通常コード部分)は
         自前LCSで通常のdiffを行い、ブロック自体はそのアンカー位置に
         対応付けて replace/insert/delete として出力する。

    before_lines が無い(ADD)ブロックはアンカーを持たないため、次に見つかった
    アンカー(無ければ a の末尾)までの区間をまとめて通常diffし、その
    diffが終わった位置にブロックを挿入する。
    MOD/DEL は変更前コードが必ず a 側に存在するはずなので、見つからない
    場合は BlockMarkerError を送出する。
    """
    # 1st pass: 各ブロックのアンカー(a側の一致位置)を先読みで求める
    anchors: List[Tuple[Optional[int], int, bool]] = []
    cursor = 0
    for blk in blocks:
        if blk.before_lines:
            pos = _find_subsequence(a, blk.before_lines, cursor)
            if pos is None:
                # MOD/DELはコメントを外した内容が変更前ファイルに必ず対応する
                # コードとして存在していないとおかしい(ADDと違い元コードが
                # あるはずの変更なので)。見つからない場合はエラーにする。
                raise BlockMarkerError(
                    f"変更前コードと対応するものが見つかりません: "
                    f"{blk.block_type} <{blk.ngy_id}> ({blk.start + 1}〜{blk.end}行目)。"
                    f"コメントを外した内容が左側ファイルの該当箇所と一致しているか確認してください。"
                )
            anchors.append((pos, len(blk.before_lines), True))
            cursor = pos + len(blk.before_lines)
        else:
            anchors.append((None, 0, True))  # ADDは元コードが無いのが正解

    # アンカーが無いブロックのために、後方にある最も近いアンカー位置を求めておく
    upper_bounds: List[int] = [len(a)] * len(blocks)
    next_known = len(a)
    for idx in range(len(blocks) - 1, -1, -1):
        pos, _, _ = anchors[idx]
        if pos is not None:
            next_known = pos
        upper_bounds[idx] = next_known

    opcodes: List[Opcode] = []
    annotations: List[dict] = []
    a_cursor = 0
    b_cursor = 0

    for blk, (pos, before_len, matched), upper in zip(blocks, anchors, upper_bounds):
        gap_b_len = blk.start - b_cursor
        if pos is not None:
            gap_a_end = pos
        else:
            # アンカーが無い場合、直前の通常コード部分はほぼ1対1で並んでいる
            # という前提で、gap_bと同じ行数だけ(次のアンカーを超えない範囲で)
            # a側を対象にする。
            gap_a_end = min(a_cursor + gap_b_len, upper)
        gap_a = list(a[a_cursor:gap_a_end])
        gap_b = list(b[b_cursor:blk.start])
        for tag, gi1, gi2, gj1, gj2 in _lcs_opcodes(gap_a, gap_b):
            opcodes.append((tag, a_cursor + gi1, a_cursor + gi2, b_cursor + gj1, b_cursor + gj2))

        real_pos = pos if pos is not None else gap_a_end

        if before_len == 0 and not blk.after_lines:
            block_tag = None
        elif before_len == 0:
            block_tag = "insert"
        elif not blk.after_lines:
            block_tag = "delete"
        else:
            block_tag = "replace"

        if block_tag:
            opcodes.append((block_tag, real_pos, real_pos + before_len, blk.start, blk.end))

        annotations.append(
            {
                "block_type": blk.block_type,
                "ngy_id": blk.ngy_id,
                "matched": matched,
                "a_range": (real_pos, real_pos + before_len),
                "b_range": (blk.start, blk.end),
                "tag": block_tag,
            }
        )

        a_cursor = real_pos + before_len
        b_cursor = blk.end

    gap_a = list(a[a_cursor:])
    gap_b = list(b[b_cursor:])
    for tag, gi1, gi2, gj1, gj2 in _lcs_opcodes(gap_a, gap_b):
        opcodes.append((tag, a_cursor + gi1, a_cursor + gi2, b_cursor + gj1, b_cursor + gj2))

    return opcodes, annotations


class PlainSequenceMatcher:
    """difflib.SequenceMatcher の代替となる、ブロックマーカーを扱わない
    シンプルなLCSベースdiffクラス(difflib非依存)。"""

    def __init__(self, isjunk=None, a: Sequence[str] = (), b: Sequence[str] = (), autojunk: bool = True):
        self.set_seqs(a, b)

    def set_seqs(self, a: Sequence[str], b: Sequence[str]) -> None:
        self.a = list(a)
        self.b = list(b)
        self._opcodes = _lcs_opcodes(self.a, self.b)

    def get_opcodes(self) -> List[Opcode]:
        return list(self._opcodes)

    def get_matching_blocks(self) -> List[MatchingBlock]:
        blocks: List[MatchingBlock] = []
        for tag, i1, i2, j1, j2 in self._opcodes:
            if tag == "equal":
                blocks.append((i1, j1, i2 - i1))
        blocks.append((len(self.a), len(self.b), 0))
        return blocks

    def ratio(self) -> float:
        matches = sum(i2 - i1 for tag, i1, i2, j1, j2 in self._opcodes if tag == "equal")
        total = len(self.a) + len(self.b)
        return 2.0 * matches / total if total else 1.0

    quick_ratio = ratio
    real_quick_ratio = ratio


class JavaBlockSequenceMatcher:
    """difflib.SequenceMatcher と互換のインタフェースを持つブロック単位diffクラス。

    b(通常は変更後/right側のファイル)にADD/MOD/DELマーカーが含まれている
    ことを想定する。a(変更前/left側)は無印の通常コードでよい。
    """

    def __init__(
        self,
        isjunk=None,
        a: Sequence[str] = (),
        b: Sequence[str] = (),
        autojunk: bool = True,
    ):
        # isjunk / autojunk は difflib.SequenceMatcher とのシグネチャ互換のために
        # 受け取るのみで、このシンプル実装では使用しない。
        self.set_seqs(a, b)

    def set_seqs(self, a: Sequence[str], b: Sequence[str]) -> None:
        self.a = list(a)
        self.b = list(b)
        # マーカーのペア崩れはどちら側にあってもエラーにする
        parse_blocks(self.a)
        self._blocks = parse_blocks(self.b)
        self._opcodes, self._annotations = _diff_with_blocks(self.a, self.b, self._blocks)

    def get_opcodes(self) -> List[Opcode]:
        return list(self._opcodes)

    def get_matching_blocks(self) -> List[MatchingBlock]:
        blocks: List[MatchingBlock] = []
        for tag, i1, i2, j1, j2 in self._opcodes:
            if tag == "equal":
                blocks.append((i1, j1, i2 - i1))
        blocks.append((len(self.a), len(self.b), 0))
        return blocks

    def get_block_annotations(self) -> List[dict]:
        """ADD/MOD/DELブロックと変更前コードの対応付け一覧を返す(difflibにはない拡張)。"""
        return list(self._annotations)

    def ratio(self) -> float:
        matches = sum(i2 - i1 for tag, i1, i2, j1, j2 in self._opcodes if tag == "equal")
        total = len(self.a) + len(self.b)
        return 2.0 * matches / total if total else 1.0

    quick_ratio = ratio
    real_quick_ratio = ratio


def java_block_diff(
    a: Sequence[str],
    b: Sequence[str],
    lineterm: str = "\n",
    fromfile: str = "",
    tofile: str = "",
) -> List[str]:
    """unified diff相当の出力を、ブロック単位で生成するヘルパー。"""
    sm = JavaBlockSequenceMatcher(None, a, b)
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
        description="Javaのブロック(ADD/MOD/DEL開始・終了 <NGY-xxx>)単位でdiffを出すツール"
    )
    p.add_argument("left")
    p.add_argument("right")
    p.add_argument("--encoding", default="utf-8")
    p.add_argument("-o", "--output", default=None)
    p.add_argument(
        "--show-blocks",
        action="store_true",
        help="ADD/MOD/DELブロックと変更前コードの対応付け情報を併せて表示する",
    )
    args = p.parse_args(argv)

    left_lines = read_lines(args.left, args.encoding)
    right_lines = read_lines(args.right, args.encoding)

    try:
        sm = JavaBlockSequenceMatcher(None, left_lines, right_lines)
    except BlockMarkerError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    diff_lines = java_block_diff(left_lines, right_lines, fromfile=args.left, tofile=args.right)

    if args.output:
        with open(args.output, "w", encoding=args.encoding, newline="") as f:
            f.writelines(diff_lines)
    else:
        sys.stdout.writelines(diff_lines)

    if args.show_blocks:
        for ann in sm.get_block_annotations():
            a1, a2 = ann["a_range"]
            b1, b2 = ann["b_range"]
            matched = "OK" if ann["matched"] else "対応行が見つかりません"
            print(
                f"# {ann['block_type']} <{ann['ngy_id']}>: "
                f"left[{a1}:{a2}] <-> right[{b1}:{b2}] ({matched})",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
