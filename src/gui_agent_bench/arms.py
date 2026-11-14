"""Stable public arm identifiers and artifact names."""

from enum import Enum


class Arm(str, Enum):
    JUDGE_VISUAL = "judge_visual"
    JUDGE_TEST = "judge_test"
    ORACLE_VISUAL = "oracle_visual"
    ORACLE_UI = "oracle_ui"
    TEST_VISUAL = "test_visual"
    TEST_UI = "test_ui"


ARM_IDS = tuple(arm.value for arm in Arm)


def generated(arm):
    return arm.startswith(('oracle_', 'test_'))


def artifact_name(arm):
    return 'test.py' if arm.startswith('test_') else 'oracle.py' if generated(arm) else 'judgment.json'


def abi(arm, platform='web'):
    return 'visual-v1-' + platform if generated(arm) else 'judge-v1'
