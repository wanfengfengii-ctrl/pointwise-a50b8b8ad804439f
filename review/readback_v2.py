from .register import OverlapReport, ReportRegister, ReviewReceipt


def read_v2(register: ReportRegister, report_id: int) -> tuple[OverlapReport, ReviewReceipt]:
    return register.load_v2(report_id)
