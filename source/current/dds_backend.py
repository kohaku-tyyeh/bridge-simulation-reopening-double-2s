"""Small typed binding to the DDS 2.x library distributed with endplay.

Load the shared library directly to cap threads before allocation; importing
endplay itself requests host-wide threading automatically. Public tables use
strains CDHSN and seats NESW. DDS internally uses SHDCN and NESW.
"""
import ctypes as C
from importlib.metadata import distribution, version
import json
from pathlib import Path
import time


class PBNDeal(C.Structure):
    _fields_ = [("cards", C.c_char * 80)]


class Table(C.Structure):
    _fields_ = [("resTable", (C.c_int * 4) * 5)]


class PBNDeals(C.Structure):
    _fields_ = [("noOfTables", C.c_int), ("deals", PBNDeal * 200)]


class Tables(C.Structure):
    _fields_ = [("noOfBoards", C.c_int), ("results", Table * 200)]


class ParResults(C.Structure):
    _fields_ = [("scores", (C.c_char * 16) * 2),
                ("contracts", (C.c_char * 128) * 2)]


class AllParResults(C.Structure):
    _fields_ = [("results", ParResults * 40)]


def pbn(record):
    return "N:" + " ".join(".".join(record["hands"][seat]["suits"][suit]
                                     for suit in "SHDC") for seat in "NESW")


class DDS:
    def __init__(self, threads=2):
        path = distribution("endplay").locate_file("endplay/_dds/libdds.so")
        self.library_path = str(path)
        self.endplay_version = version("endplay")
        self.lib = C.CDLL(str(path))
        self.lib.SetMaxThreads.argtypes = [C.c_int]
        self.lib.SetMaxThreads.restype = None
        self.lib.SetMaxThreads(threads)
        self.lib.CalcDDtablePBN.argtypes = [PBNDeal, C.POINTER(Table)]
        self.lib.CalcDDtablePBN.restype = C.c_int
        self.lib.CalcAllTablesPBN.argtypes = [C.POINTER(PBNDeals), C.c_int,
            C.POINTER(C.c_int), C.POINTER(Tables), C.POINTER(AllParResults)]
        self.lib.CalcAllTablesPBN.restype = C.c_int
        self.lib.ErrorMessage.argtypes = [C.c_int, C.c_char_p]
        self.lib.ErrorMessage.restype = None

    def check(self, result):
        if result != 1:
            error = C.create_string_buffer(80)
            self.lib.ErrorMessage(result, error)
            raise RuntimeError(f"DDS {result}: {error.value.decode()}")

    @staticmethod
    def convert(table):
        return [[int(table.resTable[s][p]) for p in range(4)]
                for s in [3, 2, 1, 0, 4]]

    def table(self, deal_pbn):
        deal = PBNDeal(deal_pbn.encode("ascii"))
        result = Table()
        self.check(self.lib.CalcDDtablePBN(deal, C.byref(result)))
        return self.convert(result)

    def tables(self, deal_pbns):
        if not 1 <= len(deal_pbns) <= 40:
            raise ValueError("DDS all-strain batches must have 1..40 deals")
        deals, results, ignored_par = PBNDeals(), Tables(), AllParResults()
        deals.noOfTables = len(deal_pbns)
        for i, value in enumerate(deal_pbns):
            deals.deals[i].cards = value.encode("ascii")
        self.check(self.lib.CalcAllTablesPBN(C.byref(deals), -1,
            (C.c_int * 5)(0, 0, 0, 0, 0), C.byref(results), C.byref(ignored_par)))
        return [self.convert(results.results[i]) for i in range(len(deal_pbns))]


def generate_cache(deals_path, cache_path, threads=2):
    records = json.loads(Path(deals_path).read_text())["deals"]
    cache_path = Path(cache_path)
    cached = []
    if cache_path.exists():
        cached = [json.loads(line) for line in cache_path.read_text().splitlines()]
    for record, row in zip(records, cached):
        assert row["number"] == record["number"] and row["pbn"] == pbn(record)
    if len(cached) > len(records):
        raise ValueError("Cache belongs to a larger/different deal set")
    engine = DDS(threads)
    started = time.monotonic()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("a", buffering=1) as f:
        for i in range(len(cached), len(records), 20):
            batch = records[i:i+20]
            pbns = [pbn(d) for d in batch]
            tables = engine.tables(pbns)
            for record, text, table in zip(batch, pbns, tables):
                assert all(0 <= t <= 13 for row in table for t in row)
                f.write(json.dumps(dict(number=record["number"], pbn=text,
                                        dd_table_CDHSN_NESW=table)) + "\n")
            if (i + len(batch)) % 100 == 0:
                print(f"DDS {i+len(batch)}/{len(records)}; {time.monotonic()-started:.1f}s", flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("deals", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    generate_cache(args.deals, args.cache, args.threads)
