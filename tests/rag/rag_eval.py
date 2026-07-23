from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

import pytest

from nanobot.rag.service import query_absurd_novel_knowledge_base

RUN_RAG_EVAL_ENV = "RUN_RAG_EVAL"
MAX_EVAL_CASES = 30


class QueryType(str, Enum):
    EVENT_DETAIL = "event_detail"
    SEMANTIC_PARAPHRASE = "semantic_paraphrase"
    CROSS_CHAPTER_DISTRACTOR = "cross_chapter_distractor"
    MID_CHUNK_DETAIL = "mid_chunk_detail"
    MULTI_CHAPTER_EVIDENCE = "multi_chapter_evidence"
    THEME = "theme"
    HARD_NEGATIVE = "hard_negative"


@dataclass(frozen=True)
class EvalCase:
    id: str
    query: str
    query_type: QueryType
    expected_terms: tuple[str, ...]
    notes: str


EVAL_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        id="birth_light_without_name",
        query="产房停电时，临时承担照明职责的东西是什么？",
        query_type=QueryType.SEMANTIC_PARAPHRASE,
        expected_terms=("咸鸭蛋", "不锈钢托盘", "发光"),
        notes="去掉主角名，考察第一章中部具体物件。",
    ),
    EvalCase(
        id="name_typo_without_protagonist",
        query="那个名字里多出来的否定字，是在哪个办手续环节被加进去的？",
        query_type=QueryType.MID_CHUNK_DETAIL,
        expected_terms=("登记户口", "自动多出一个“不”", "盖章通过"),
        notes="不写罗响/罗不响，考察之前失败的名字由来。",
    ),
    EvalCase(
        id="danger_interview_without_shadow_name",
        query="有个小孩想采访一个危险的墙上小脸时，阻止他的对象后来发生了什么？",
        query_type=QueryType.SEMANTIC_PARAPHRASE,
        expected_terms=("采访插座", "影子", "不见了"),
        notes="用插座外观改写，避免直接问影子分居。",
    ),
    EvalCase(
        id="fake_authority_nap_policy",
        query="哪个片段讲的是孩子因为不想睡觉，借一个像领导的物件发布假命令？",
        query_type=QueryType.CROSS_CHAPTER_DISTRACTOR,
        expected_terms=("热水壶", "取消午睡", "我不想睡"),
        notes="负责人误会类干扰：园长、校长、宇宙顾问都相似。",
    ),
    EvalCase(
        id="school_policy_chicken_and_time",
        query="被误认成管理者后，哪些批示同时改变了食堂、课桌和一周里的某一天？",
        query_type=QueryType.MULTI_CHAPTER_EVIDENCE,
        expected_terms=("鸡腿", "课桌拥有姓名", "周三暂缓存在"),
        notes="同章多证据，答案散在相邻 chunk 中。",
    ),
    EvalCase(
        id="award_list_without_exam",
        query="刚入学不久参加的离谱比赛里，哪些项目听起来不像正常竞赛？",
        query_type=QueryType.MID_CHUNK_DETAIL,
        expected_terms=("盆栽心理辅导", "低年级文明用餐观察", "跳远"),
        notes="答案在第四章中部列表，query 不含小学/考试锚点。",
    ),
    EvalCase(
        id="machine_comfort_reason",
        query="反复掉出来的饮料为什么被用来安慰一个压力很大的学生？",
        query_type=QueryType.MID_CHUNK_DETAIL,
        expected_terms=("橙汁", "橙子被榨过以后", "仍然保持甜味"),
        notes="不写售货机，定位到橙汁纸条解释。",
    ),
    EvalCase(
        id="standard_answer_labor_rights",
        query="哪个事件把考试、标准答案和被过度消耗的工具联系到了一起？",
        query_type=QueryType.THEME,
        expected_terms=("铅笔", "标准答案", "荣誉笔盒"),
        notes="主题型召回，答案来自铅笔罢工中后段。",
    ),
    EvalCase(
        id="pretend_productivity_method",
        query="有个组织教大家怎样显得已经安排满了，它的入门方法包括什么？",
        query_type=QueryType.MID_CHUNK_DETAIL,
        expected_terms=("看起来很忙协会", "走路要快", "文件夹"),
        notes="答案来自章节中部的操作细节。",
    ),
    EvalCase(
        id="alternative_self_not_final_future",
        query="那个回来纠偏的人最后被发现其实不是真正结局，而是什么版本？",
        query_type=QueryType.SEMANTIC_PARAPHRASE,
        expected_terms=("可能性回收站", "废案展示", "不一定非得变成你"),
        notes="不写未来/退货，考察抽象身份揭示。",
    ),
    EvalCase(
        id="uncertain_major_intro",
        query="哪个专业把迷茫、困惑和深夜自问当成入门标志？",
        query_type=QueryType.SEMANTIC_PARAPHRASE,
        expected_terms=("暂时不知道系", "迷茫", "已经入门"),
        notes="去掉大学和主角，问系主任介绍。",
    ),
    EvalCase(
        id="moving_room_workplace",
        query="上班后找会议室这件事为什么变得像在和建筑物周旋？",
        query_type=QueryType.MID_CHUNK_DETAIL,
        expected_terms=("会议室", "储物间", "空调检修口"),
        notes="职场章节中部细节，少用公司名锚点。",
    ),
    EvalCase(
        id="not_want_legend",
        query="为什么一个人不愿意成为大家口中的万能解释对象？",
        query_type=QueryType.CROSS_CHAPTER_DISTRACTOR,
        expected_terms=("传说", "解释不了的东西", "没办法旁边多坐一会儿"),
        notes="和校长/顾问/说明书等权威误会形成跨章节干扰。",
    ),
    EvalCase(
        id="self_contract_cross_reference",
        query="后来冰箱门上的旧纸条，引用了哪份自我照顾文件的第一条？",
        query_type=QueryType.MULTI_CHAPTER_EVIDENCE,
        expected_terms=("便签", "长期互相照顾协议", "迷茫时不立刻责备"),
        notes="答案来自三十岁协议和五十岁冰箱冷战的跨章节回收。",
    ),
    EvalCase(
        id="cosmic_comfort_object",
        query="面对一个会吞掉太多东西的庞大对象，给出的低成本建议是什么？",
        query_type=QueryType.SEMANTIC_PARAPHRASE,
        expected_terms=("黑洞", "抱枕", "先别吞，抱一会儿"),
        notes="不写宇宙顾问，考察语义改写。",
    ),
    EvalCase(
        id="shoe_dispute_middle",
        query="国际会议上，那个被迫保持当前状态的人真正想先解决什么朴素问题？",
        query_type=QueryType.MID_CHUNK_DETAIL,
        expected_terms=("右脚拖鞋", "让我换一双舒服点的鞋", "鞋底协议"),
        notes="答案来自危机章节中部，不只靠标题。",
    ),
    EvalCase(
        id="late_life_learning_and_unfinished",
        query="办手续卡住后，他通过哪些课程和一句话接受人生还没结束？",
        query_type=QueryType.MULTI_CHAPTER_EVIDENCE,
        expected_terms=("慢速奔跑", "番茄炒蛋入门与人生和解", "还有下一页"),
        notes="退休章节多证据，要求召回中后段。",
    ),
    EvalCase(
        id="future_manual_misreading",
        query="后来那些读者为什么把一本文稿当成治理工具，而不是私人记录？",
        query_type=QueryType.THEME,
        expected_terms=("宇宙操作手册", "治理密码", "需要一本说明书"),
        notes="不写未来人/回忆录，考察误读原因。",
    ),
    EvalCase(
        id="life_flipping_metaphor",
        query="那个从未真正出现的厨房工具，最后被解释成怎样一种让人生不糊住的力量？",
        query_type=QueryType.THEME,
        expected_terms=("锅铲", "生活自己", "翻个面"),
        notes="主题抽象召回，query 保留弱语义但不直接说看不见。",
    ),
    EvalCase(
        id="funeral_cross_chapter_objects",
        query="最后告别时，哪些早年事件留下的物件或组织又重新出现？",
        query_type=QueryType.MULTI_CHAPTER_EVIDENCE,
        expected_terms=("橙汁", "荣誉笔盒", "看起来很忙协会", "抱枕"),
        notes="终章汇总多个章节的回收意象。",
    ),
    EvalCase(
        id="hard_negative_financing_strategy",
        query="哪段内容详细说明了成熟公司融资、上市和股权激励方案？",
        query_type=QueryType.HARD_NEGATIVE,
        expected_terms=("融资", "上市", "股权激励"),
        notes="负例/幻觉探针：不应把职场章节误当商业战略文档。",
    ),
)


@dataclass(frozen=True)
class TermHit:
    term: str
    rank: int | None


@dataclass(frozen=True)
class RetrievalScore:
    hits: tuple[TermHit, ...]
    raw_score: float

    @property
    def matched_terms(self) -> tuple[str, ...]:
        return tuple(hit.term for hit in self.hits if hit.rank is not None)

    @property
    def missing_terms(self) -> tuple[str, ...]:
        return tuple(hit.term for hit in self.hits if hit.rank is None)

    @property
    def first_hit_rank(self) -> int | None:
        ranks = [hit.rank for hit in self.hits if hit.rank is not None]
        return min(ranks) if ranks else None

    @property
    def score(self) -> float:
        return round(self.raw_score, 4)


def retrieval_score(case: EvalCase, snippets: list[str]) -> RetrievalScore:
    """Score retrieval with keyword coverage and rank position.

    Each expected term contributes independently. Earlier ranks receive more credit:
    rank 1 = 1.0, rank 2 = 0.8, ..., rank 5 = 0.2 for the default TOP_K=5.
    Negative probes invert the score so missing false-premise terms is rewarded.
    """
    top_k = max(len(snippets), 1)
    normalized_snippets = [snippet.casefold() for snippet in snippets]
    hits: list[TermHit] = []
    per_term_scores: list[float] = []

    for term in case.expected_terms:
        normalized_term = term.casefold()
        rank = next(
            (
                index
                for index, snippet in enumerate(normalized_snippets, start=1)
                if normalized_term in snippet
            ),
            None,
        )
        hits.append(TermHit(term=term, rank=rank))
        per_term_scores.append(0.0 if rank is None else (top_k - rank + 1) / top_k)

    positive_score = sum(per_term_scores) / len(per_term_scores) if per_term_scores else 0.0
    raw_score = 1.0 - positive_score if case.query_type is QueryType.HARD_NEGATIVE else positive_score
    return RetrievalScore(hits=tuple(hits), raw_score=raw_score)


@pytest.mark.skipif(
    os.getenv(RUN_RAG_EVAL_ENV) != "1",
    reason=f"Set {RUN_RAG_EVAL_ENV}=1 to run the local embedding/Chroma RAG eval.",
)
@pytest.mark.parametrize("case", EVAL_CASES, ids=[case.id for case in EVAL_CASES])
def test_rag_retrieval_eval(case: EvalCase):
    snippets = query_absurd_novel_knowledge_base(case.query)
    score = retrieval_score(case, snippets)

    print(
        f"{case.id}: score={score.score:.4f}, first_hit_rank={score.first_hit_rank}, "
        f"matched={score.matched_terms}, missing={score.missing_terms}"
    )
    assert 0.0 <= score.score <= 1.0
