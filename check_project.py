"""Run this project's full unittest suite from the repository root."""
import sys
import unittest

from overlap_example import v2_demo


def main():
    suite = unittest.defaultTestLoader.discover('tests', top_level_dir='.')
    if suite.countTestCases():
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    else:
        print('No tests discovered in tests/', file=sys.stderr)
        result = unittest.TestResult()
    for status, failed_cases in (
        ('FAIL', (test for test, _ in result.failures)),
        ('ERROR', (test for test, _ in result.errors)),
        ('UNEXPECTED_SUCCESS', result.unexpectedSuccesses),
    ):
        for test in failed_cases:
            print(f'{status} {test.id()}')
    successful = result.testsRun > 0 and result.wasSuccessful()

    # V2 联合场景门：关站签发、接纳、上下界见证与重开领取必须端到端成立。
    if successful:
        from overlap_example import CASES
        demo = v2_demo()
        expected = {case['name']: tuple(case['expected_bounds']) for case in CASES}
        for case in demo['cases']:
            if tuple(case['bounds']) != expected[case['name']]:
                print(f"V2_JOINT_FAIL {case['name']} bounds={case['bounds']}")
                successful = False
            if case.get('reopened_report_id') is None:
                print(f"V2_JOINT_FAIL {case['name']} missing reopened report")
                successful = False
        if successful:
            print(f"V2_JOINT_SCENARIO cases={len(demo['cases'])} result=PASS")

    print(f'TEST SUMMARY total={result.testsRun} failures={len(result.failures)} '
          f'errors={len(result.errors)} skipped={len(result.skipped)} '
          f'expected_failures={len(result.expectedFailures)} '
          f'unexpected_successes={len(result.unexpectedSuccesses)} '
          f'result={"PASS" if successful else "FAIL"}')
    return 0 if successful else 1


if __name__ == '__main__':
    raise SystemExit(main())
