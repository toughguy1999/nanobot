"""Deterministic, line-aware head/tail clipping of one tool body."""

from nanobot.agent.compress.token_estimate import character_weight, estimate_tokens

DEFAULT_MAX_TOOL_RESULT_TOKENS = 4000
CLIP_NOTICE = "\n\n[超出预算部分已裁剪]\n\n"


def _prefix_end(text: str, budget: int) -> int:
    weight = 0
    end = 0
    for char in text:
        weight += character_weight(char)
        if weight > budget * 4:
            break
        end += 1
    if 0 < end < len(text) and text[end - 1:end + 1] == "\r\n":
        end -= 1
    return end


def compress_tool_result(text: str, budget: int = DEFAULT_MAX_TOOL_RESULT_TOKENS) -> str:
    if budget <= 0:
        return ""
    if estimate_tokens(text) <= budget:
        return text
    notice_cost = estimate_tokens(CLIP_NOTICE)
    if budget < notice_cost:
        return CLIP_NOTICE[:_prefix_end(CLIP_NOTICE, budget)]

    remaining = budget - notice_cost
    head_end = _prefix_end(text, remaining // 2)
    # Retain the last complete line if one fits; otherwise keep a partial first line.
    line_end = text.rfind("\n", 0, head_end)
    if line_end >= 0:
        head_end = line_end + 1

    weight = 0
    tail_start = len(text)
    for index in range(len(text) - 1, head_end - 1, -1):
        weight += character_weight(text[index])
        if weight > (remaining - remaining // 2) * 4:
            break
        tail_start = index
    if 0 < tail_start < len(text) and text[tail_start - 1:tail_start + 1] == "\r\n":
        tail_start += 1
    if tail_start > 0 and text[tail_start - 1] != "\n":
        line_start = text.find("\n", tail_start)
        # A trailing newline alone is not a complete last line.
        if 0 <= line_start < len(text) - 1:
            tail_start = line_start + 1
    return text[:head_end] + CLIP_NOTICE + text[tail_start:]
