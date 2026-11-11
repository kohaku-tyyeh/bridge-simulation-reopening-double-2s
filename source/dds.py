"""libdds 的 ctypes 包裝（libdds.so 取自 pip 套件 endplay 內附的檔案；只用 CalcDDtablePBN、SetMaxThreads、GetDDSInfo）。"""
import ctypes as C, hashlib, importlib.util, os
_spec = importlib.util.find_spec('endplay')
LIB = os.path.realpath(os.path.join(list(_spec.submodule_search_locations)[0], '_dds', 'libdds.so'))
_lib = C.CDLL(LIB)

class DealPBN(C.Structure):
    _fields_ = [('cards', C.c_char * 80)]
class TableRes(C.Structure):
    _fields_ = [('resTable', (C.c_int * 4) * 5)]  # [王牌 S,H,D,C,NT][莊家 N,E,S,W]
class DDSInfo(C.Structure):
    _fields_ = [('major', C.c_int), ('minor', C.c_int), ('patch', C.c_int),
                ('idString', C.c_char * 10), ('system', C.c_int), ('numBits', C.c_int),
                ('compiler', C.c_int), ('constructor', C.c_int), ('numCores', C.c_int),
                ('threading', C.c_int), ('noOfThreads', C.c_int),
                ('threadSizes', C.c_char * 128), ('systemString', C.c_char * 1024)]

_lib.CalcDDtablePBN.argtypes = [DealPBN, C.POINTER(TableRes)]
_lib.CalcDDtablePBN.restype = C.c_int

def info():
    _lib.SetMaxThreads(1)  # 未初始化時 GetDDSInfo 會當掉
    d = DDSInfo(); _lib.GetDDSInfo(C.byref(d))
    return dict(GetDDSInfo=d.idString.decode(), library='endplay/_dds/libdds.so',
                sha256=hashlib.sha256(open(LIB, 'rb').read()).hexdigest())

def set_threads(n):
    _lib.SetMaxThreads(n)

STRAINS = 'SHDCN'; SEATS = 'NESW'
def table(pbn):
    """回傳 dict[(王牌, 座位)] = 該座位作莊、該王牌的雙夢家墩數；王牌 SHDCN，座位 NESW。"""
    r = TableRes()
    rc = _lib.CalcDDtablePBN(DealPBN(pbn.encode()), C.byref(r))
    if rc != 1:
        raise RuntimeError(f'DDS error {rc} on {pbn}')
    return {(STRAINS[s], SEATS[h]): r.resTable[s][h] for s in range(5) for h in range(4)}
