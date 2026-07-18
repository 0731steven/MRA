"""Deterministic, auditable teaching-package generation from the question bank."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .analytics import PREREQUISITES


LESSON_TYPES = {
    "concept": "新授概念课",
    "review": "复习整合课",
    "remediation": "纠错补救课",
    "assessment": "诊断讲评课",
}

LEARNER_PROFILES = {
    "mixed": "基础差异较大的混合班级",
    "foundation": "整体需要更多脚手架",
    "advanced": "整体基础较稳、需要迁移挑战",
}

LAYER_CONFIG = {
    "foundation": {
        "label": "起步任务",
        "difficulty": "易",
        "fit": "需要确认概念边界、公式条件和基本运算的学生",
        "success": "独立完成至少 80%，并能口述所用定义或公式的适用条件",
        "next": "达标后进入进阶任务；若未达标，先完成教师给出的前置知识微讲解",
    },
    "progress": {
        "label": "进阶任务",
        "difficulty": "中",
        "fit": "基础概念基本稳定，但需要把条件翻译成模型的学生",
        "success": "独立完成至少 70%，关键建模步骤和理由完整",
        "next": "达标后进入迁移挑战；若卡住，回到起步任务中的同知识点题目对照条件",
    },
    "transfer": {
        "label": "迁移挑战",
        "difficulty": "难",
        "fit": "能够独立完成常规题，需要检验陌生情境迁移的学生",
        "success": "在无提示条件下给出完整策略，并能解释条件变化如何影响结论",
        "next": "完成后承担同伴讲评或变式设计；若证据不足，不据此直接判定为已掌握",
    },
}


def _allocate_minutes(duration: int, lesson_type: str) -> list[int]:
    weights = {
        "concept": [0.11, 0.22, 0.24, 0.30, 0.13],
        "review": [0.15, 0.15, 0.25, 0.32, 0.13],
        "remediation": [0.18, 0.20, 0.25, 0.25, 0.12],
        "assessment": [0.16, 0.14, 0.24, 0.31, 0.15],
    }.get(lesson_type, [0.11, 0.22, 0.24, 0.30, 0.13])
    total = max(15, min(int(duration), 180))
    result = [max(2, int(total * weight)) for weight in weights]
    while sum(result) < total:
        index = max(range(len(weights)), key=lambda item: weights[item] - result[item] / total)
        result[index] += 1
    while sum(result) > total:
        index = max((item for item in range(len(result)) if result[item] > 2), key=result.__getitem__)
        result[index] -= 1
    return result


def _pick_structure(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    buckets = {
        difficulty: [row for row in rows if row.get("hard_level") == difficulty]
        for difficulty in ("易", "中", "难")
    }
    diagnostic = (buckets["易"] or buckets["中"] or buckets["难"] or rows)[0]
    exit_candidates = [*reversed(buckets["中"]), *reversed(buckets["难"]), *reversed(rows)]
    exit_ticket = next((row for row in exit_candidates if row["ID"] != diagnostic["ID"]), diagnostic)
    reserved = {diagnostic["ID"], exit_ticket["ID"]}
    layers = {
        "foundation": [row for row in buckets["易"] if row["ID"] not in reserved][:3],
        "progress": [row for row in buckets["中"] if row["ID"] not in reserved][:4],
        "transfer": [row for row in buckets["难"] if row["ID"] not in reserved][:3],
    }
    return {"diagnostic": diagnostic, "exit_ticket": exit_ticket}, layers


def _question_markdown(row: dict[str, Any], index: int) -> str:
    choices = row.get("choices") or []
    choices_text = "\n" + "\n".join(f"- {choice}" for choice in choices) if choices else ""
    keypoints = "、".join(row.get("keypoint") or []) or "未标注"
    return (
        f"### {index}. {row['ID']} · {row.get('qtype') or '题目'} · {row.get('hard_level') or '未标难度'}\n\n"
        f"**考查：** {keypoints}\n\n{row.get('question') or '题干缺失'}{choices_text}\n\n"
        "**作答要求：** 写出判断依据或关键中间步骤；只写最终结果不能作为完全达标证据。\n"
    )


def _teacher_prompts(keypoints: list[str]) -> list[str]:
    joined = " ".join(keypoints)
    if any(name in joined for name in ("贝叶斯", "条件概率", "全概率")):
        return [
            "先不计算：题目中的目标事件、已知证据和可能原因分别是什么？",
            "分母为什么要覆盖全部互斥情形？漏掉一个情形会破坏哪一步？",
            "如果交换条件概率的两个事件，原结论为什么通常不再成立？",
        ]
    if any(name in joined for name in ("分布", "密度", "分布列", "随机变量")):
        return [
            "随机变量如何把样本点映射成数值？先说对象，再写公式。",
            "这个函数满足成为分布列或密度的哪些必要条件？",
            "区间端点、离散取值或归一化条件改变后，结论如何变化？",
        ]
    if any(name in joined for name in ("数学期望", "方差", "协方差")):
        return [
            "计算前先判断：这里要求的是位置、波动还是共同变化？",
            "哪些运算可以直接利用线性性质，哪些步骤必须保留交叉项？",
            "结果的数量级和符号是否符合随机变量的实际含义？",
        ]
    if any(name in joined for name in ("估计", "置信", "检验", "统计量")):
        return [
            "总体、参数、样本和统计量分别是什么？先完成对象对齐。",
            "这个方法依赖哪些分布假设？若假设不满足，哪一步首先失效？",
            "统计结论能说明什么、不能说明什么？请用完整语句解释。",
        ]
    return [
        "题目给出的对象、条件和目标量分别是什么？",
        "为什么选择这个定义或公式，而不是相邻的另一个方法？",
        "改变一个条件后，原推理中的哪一步需要重做？",
    ]


def _misconceptions(keypoints: list[str], insights: dict[str, Any]) -> list[str]:
    observed = [item["name"] for item in insights.get("diagnostics", {}).get("error_types", [])[:3]]
    result = [f"班级历史作答已观察到：{name}" for name in observed]
    prerequisites = []
    for keypoint in keypoints:
        prerequisites.extend(PREREQUISITES.get(keypoint, []))
    if prerequisites:
        result.append(f"前置知识未稳定：{'、'.join(dict.fromkeys(prerequisites))}")
    result.extend(["公式适用条件未写清就直接代入", "只给结果，缺少可检查的建模或推理证据"])
    return list(dict.fromkeys(result))[:4]


def _layer_markdown(layer: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    if not rows:
        questions = "当前题库检索结果中没有该难度题。教师应补充题目后再将本层发布给学生。"
    else:
        questions = "\n\n".join(_question_markdown(row, index) for index, row in enumerate(rows, 1))
    return (
        f"## {layer['label']}\n\n"
        f"- **适用证据：** {layer['fit']}\n"
        f"- **达标标准：** {layer['success']}\n"
        f"- **下一步规则：** {layer['next']}\n\n{questions}"
    )


def build_teaching_package(
    *,
    topic: str,
    duration: int,
    objectives: str,
    rows: list[dict[str, Any]],
    insights: dict[str, Any],
    lesson_type: str = "concept",
    learner_profile: str = "mixed",
    classroom_name: str | None = None,
) -> dict[str, Any]:
    """Build teacher/student artifacts plus a machine-readable manifest."""

    if not rows:
        raise ValueError("教学包至少需要一道题")
    lesson_type = lesson_type if lesson_type in LESSON_TYPES else "concept"
    learner_profile = learner_profile if learner_profile in LEARNER_PROFILES else "mixed"
    duration = max(15, min(int(duration), 180))
    keypoint_counts = Counter(str(kp) for row in rows for kp in (row.get("keypoint") or []))
    keypoints = [name for name, _count in keypoint_counts.most_common(4)]
    anchors, layer_rows = _pick_structure(rows)
    diagnostic = anchors["diagnostic"]
    exit_ticket = anchors["exit_ticket"]
    minutes = _allocate_minutes(duration, lesson_type)
    prompts = _teacher_prompts(keypoints)
    misconceptions = _misconceptions(keypoints, insights)
    attempts = int(insights.get("diagnostics", {}).get("attempts") or 0)
    evidence_note = (
        f"已关联“{classroom_name}”，本包参考了 {attempts} 次与所选题目直接相关的班级作答。"
        if classroom_name and attempts
        else f"已关联“{classroom_name}”，但当前尚无与所选题目直接相关的班级作答；先用入门诊断积累证据。"
        if classroom_name
        else "未关联具体班级；分层是可调整的教学路径，不代表对学生能力的固定判断。"
    )
    objective_items = [
        f"能识别“{keypoints[0]}”的适用条件，并指出至少一个不适用情形。" if keypoints else "能识别核心概念的适用条件。",
        f"能独立完成至少一道涉及“{'、'.join(keypoints[:2])}”的典型题，并保留关键推理步骤。" if keypoints else "能独立完成典型题并保留关键步骤。",
        "能根据出门检测的无提示作答说明当前所处层级，并选择下一步练习。",
    ]
    if objectives:
        objective_items.insert(0, f"教师自定义目标：{objectives}")
    timeline = [
        {"phase": "入门诊断", "minutes": minutes[0], "teacher_action": f"投放 {diagnostic['ID']}，先收集方法选择与条件识别证据", "student_evidence": "独立作答，不公布层级"},
        {"phase": "概念边界", "minutes": minutes[1], "teacher_action": f"围绕“{'、'.join(keypoints[:2]) or topic}”对比适用与不适用情形", "student_evidence": "口头解释并修正诊断答案"},
        {"phase": "示范与追问", "minutes": minutes[2], "teacher_action": "展示一条完整推理链，只在关键节点停下追问", "student_evidence": "补写依据，标出第一处不确定步骤"},
        {"phase": "分层独立练习", "minutes": minutes[3], "teacher_action": "按课堂证据分配起步、进阶或迁移任务，教师巡回记录错误类型", "student_evidence": "无提示完成指定路径，达标后再升级"},
        {"phase": "出门检测", "minutes": minutes[4], "teacher_action": f"统一完成 {exit_ticket['ID']}，按四级量规快速归因", "student_evidence": "提交答案、关键依据与自评"},
    ]
    manifest_layers = {
        key: {**config, "question_ids": [row["ID"] for row in layer_rows[key]]}
        for key, config in LAYER_CONFIG.items()
    }
    source_ids = [row["ID"] for row in rows]
    manifest = {
        "version": 2,
        "engine": "curriculum-engine-v2",
        "lesson_type": lesson_type,
        "lesson_type_label": LESSON_TYPES[lesson_type],
        "learner_profile": learner_profile,
        "learner_profile_label": LEARNER_PROFILES[learner_profile],
        "classroom_name": classroom_name,
        "evidence_note": evidence_note,
        "keypoints": keypoints,
        "objectives": objective_items,
        "timeline": timeline,
        "diagnostic_question_id": diagnostic["ID"],
        "exit_ticket_question_id": exit_ticket["ID"],
        "layers": manifest_layers,
        "sources": [
            {
                "id": row["ID"],
                "difficulty": row.get("hard_level"),
                "qtype": row.get("qtype"),
                "keypoints": row.get("keypoint") or [],
            }
            for row in rows
        ],
        "quality_checks": [
            {"key": "duration", "label": "课堂时间闭合", "passed": sum(item["minutes"] for item in timeline) == duration},
            {"key": "traceable", "label": "全部题目可追溯到题库", "passed": len(source_ids) == len(set(source_ids))},
            {"key": "layers", "label": "三层任务均有题目", "passed": all(item["question_ids"] for item in manifest_layers.values())},
            {"key": "answers", "label": "学生版与答案分离", "passed": True},
            {"key": "class_evidence", "label": "已使用班级作答证据", "passed": attempts > 0},
        ],
    }

    timeline_rows = "\n".join(
        f"| {item['phase']} | {item['minutes']} 分钟 | {item['teacher_action']} | {item['student_evidence']} |"
        for item in timeline
    )
    objectives_md = "\n".join(f"- [ ] {item}" for item in objective_items)
    prompts_md = "\n".join(f"{index}. {item}" for index, item in enumerate(prompts, 1))
    misconceptions_md = "\n".join(f"- {item}" for item in misconceptions)
    warnings = insights.get("warnings") or []
    warnings_md = "\n".join(f"- **{item['title']}：** {item['detail']}" for item in warnings) or "- 当前材料未发现明显结构性缺口；仍需用入门诊断确认真实学情。"
    layers_md = "\n\n".join(_layer_markdown(LAYER_CONFIG[key], layer_rows[key]) for key in ("foundation", "progress", "transfer"))
    answers_md = "\n\n".join(
        f"### {row['ID']} · {row.get('hard_level')}\n\n**参考答案**\n\n{row.get('answer') or '题库暂无标准答案'}\n\n"
        f"**讲评建议**\n\n{row.get('explanation') or '要求学生说明关键依据，并比较不同解法的适用条件。'}"
        for row in rows
    )
    teacher_content = f"""# {topic} · 分层教学执行包

> {LESSON_TYPES[lesson_type]} · {duration} 分钟 · {LEARNER_PROFILES[learner_profile]}
> 生成方式：课程规则引擎 v2；所有题目、答案与解析均来自当前题库。

## 使用前先看

{evidence_note}

本包中的“起步、进阶、迁移”是本节课的任务路径，不是固定学生标签。教师应依据入门诊断和课堂观察随时调整。

## 一、可测量目标

{objectives_md}

## 二、课堂执行表

| 环节 | 时间 | 教师动作 | 要回收的学习证据 |
| --- | ---: | --- | --- |
{timeline_rows}

## 三、入门诊断

{_question_markdown(diagnostic, 1)}

**判读规则**

- 方法和条件均清楚：可从进阶任务开始。
- 方法正确但依据不完整：先完成起步任务中的同知识点题目。
- 对象、条件或公式选择错误：先做前置知识微讲解，再开始起步任务。

## 四、教师讲授抓手

### 关键追问

{prompts_md}

### 需要观察的错误表现

{misconceptions_md}

## 五、分层学习单

{layers_md}

## 六、出门检测

{_question_markdown(exit_ticket, 1)}

### 4 分快速量规

| 得分 | 可观察表现 | 下一步 |
| ---: | --- | --- |
| 4 | 结论正确，条件、模型和关键推理完整，无提示完成 | 进入迁移或变式任务 |
| 3 | 主方法正确，有一处非关键遗漏 | 完成一题同类进阶练习 |
| 2 | 能识别部分条件，但模型或计算链不完整 | 回到起步任务并接受一次最小提示 |
| 0–1 | 对象、条件或公式选择错误 | 回补前置知识后重新诊断 |

## 七、认知断层与材料风险

{warnings_md}

## 八、课后差异化任务

- 起步路径未达标：重做对应题，提交“条件—公式—结论”三行说明。
- 进阶路径达标：完成一题同知识点、不同情境的无提示练习。
- 迁移路径达标：改写一个条件，说明原解法哪一步需要变化，并设计可验证的变式。

## 九、教师答案与讲评依据

> 以下内容仅供教师使用，不应随学生学习单一起发布。

{answers_md}
"""
    student_layers = "\n\n".join(_layer_markdown(LAYER_CONFIG[key], layer_rows[key]) for key in ("foundation", "progress", "transfer"))
    student_content = f"""# {topic} · 分层学习单

**课时：** {duration} 分钟

**使用方式：** 先独立完成入门诊断，再按教师指定的任务路径作答。任务路径可以在课堂中调整。

## 本节课目标

{objectives_md}

## 入门诊断

{_question_markdown(diagnostic, 1)}

### 我卡在了哪里？

- [ ] 不确定题目中的对象或条件
- [ ] 不确定该用哪个定义或公式
- [ ] 方法确定，但中间计算或推理卡住
- [ ] 已完成，并能解释为什么这样做

## 我的任务路径

{student_layers}

## 出门检测

{_question_markdown(exit_ticket, 1)}

### 提交前自检

- [ ] 我写出了使用公式或方法的条件
- [ ] 我保留了关键中间步骤
- [ ] 我检查了结果的范围、符号或实际意义
- [ ] 我能指出自己最不确定的一步
"""
    return {"manifest": manifest, "teacher_content": teacher_content, "student_content": student_content}
