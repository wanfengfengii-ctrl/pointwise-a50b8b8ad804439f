from .register import ReportRegister, ReviewReceipt, ReviewReport


def read_v1(register: ReportRegister, report_id: int) -> tuple[ReviewReport, ReviewReceipt]:
    return register.load(report_id)
