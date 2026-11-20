# 河湾陶瓷试片交班台账

准备岗从装片工单冻结托盘清册。白班两站按确切槽标签登记厚度读数、勘误和封存，交班员发行指定修订。关站后，夜班凭两份已接纳原件核定覆盖、重复受检、未检槽和分站均值。下一班按未检槽安排补测，并凭报告原号领回当时的双件出处、正文和回执。

## 运行

使用 Python 3.11 标准库和 SQLite。物化后的正常回归入口为 `python3 -B check_project.py`。运行 `python3 -B shift_example.py` 可以在新临时目录演示完整交班，含关站、提交失败重试和重开领取。程序遇到断言或业务错误时以失败退出。

`shift_example.initialize(directory)` 在调用方指定的目录建立样例清册与两站的初始录入，并创建清册库、两份站库和中心库的表。重复执行会使用现存清册与站内当前修订，保留勘误、发行、接纳和报告。清册库可由准备岗、两站与中心共用。站库由各自站别保管，同一站别应持续使用同一份站库。中心核账时只需清册库和中心库。仓储对象接收调用方负责关闭的 `sqlite3.Connection`，写入口自行完成事务，请在无外层待提交事务的连接上调用。

## 公开接口

| 接口 | 输入与结果 |
| --- | --- |
| `tray.freeze_tray(catalog, tray, round_id, slots)` | 接受 `PhysicalSlot(row, column, label)` 序列。行 1–2、列 1–6，实际装片位置和标签各自唯一，保留工单顺序。返回固定清册号。同盘同轮的相同清册可重复交付。 |
| `observations.record_readings(journal, catalog, station, roster_id, readings)` | 接受 `(槽标签, 读值)` 对。提交整批新修订并返回录入修订号。本清册本站未改槽继承前件。 |
| `observations.freeze_station(journal, station, revision_id)` | 封存指定录入修订并返回站内冻结号，同一录入修订可领回同一冻结号。`get_frozen_revision` 读取固定快照。 |
| `station.issue_v1(journal, catalog, outbox, frozen_id)` | 按指定冻结号发行 UTF-8 JSON 字节。`Outbox.get(frozen_id)` 可领原件。 |
| `admission.accept_v1(archive, catalog, roster_id, raw)` | 验收原始字节，返回含 `admission_id`、`raw` 和解码正文的接纳记录。`AdmissionArchive.find` 按号领取首存原件。 |
| `review.publish_v1(archive, catalog, register, first_id, second_id)` | 按给定次序选择同盘同轮同清册的异站件，原子签出 `(ReviewReport, ReviewReceipt)`。报告正文中的来源与分站计量按选件次序对应。 |
| `review.read_v1(register, report_id)` | 返回已保存的 `(ReviewReport, ReviewReceipt)`，报告的 `body` 含 `coverage`、`stations`、`sources` 和清册身份。 |

输入读值为 `int`、`Fraction` 或整数对 `[分子, 正分母]`。`None` 表示明确缺测，零值计入有效测次。读值单位为微米，读值和及均值按有理数保存。空站的受检槽为空、有效数和读值和为零，均值为空。来件槽表必须按冻结清册序，内部计数必须等于受检槽数。中心核验件内可以对账的字段，使用站端交付的精确读值和。等值分数和 JSON 编码空白不影响等价重投，首存字节保持原样。

未知清册、修订、发行件、接纳号或报告号报 `KeyError`。非法位置、异清册槽、非法读值、坏件、来源冲突和选件失配报 `ValueError`。SQLite 写入失败会回滚本次成果并传播异常。报告和回执可以用原选件重试，旧报告按原号领取。

## 手算交班

样例清册顺序为 a、b、c。甲站 a=0、b=3，乙站 b=1、c 明确缺测。覆盖 a、b，重复 b，未检 c，计数依次为 2、1、1。甲站均值为 `(0+3)/2 = 3/2`，乙站均值为 `1/1 = 1`。下一班从原报告的未检槽领取 c 作为补测位置。
