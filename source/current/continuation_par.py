"""Exact continuation-auction Par, backed by continuation_par.cpp.

DD table rows CDHSN; columns NESW. Scores use the NS viewpoint.
Actions are bid indices 0..34, -1 Pass, -2 Double, -3 Redouble.
"""
import ctypes
from dataclasses import dataclass
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).parent
SOURCE=ROOT/'continuation_par.cpp'
LIBRARY=ROOT/'libcontinuation_par.so'
_lib=None

@dataclass(frozen=True)
class AuctionState:
    bid: int=8
    declarer: int=1
    doubled: int=1
    passes: int=0
    next_player: int=3
    # First-bidder entries are 0 unset, 1 N/E, 2 S/W, grouped NS then EW.
    first_decl: tuple=((0,0,0,0,1),(0,0,1,1,0))

def _library():
    global _lib
    if _lib is None:
        if not LIBRARY.exists() or LIBRARY.stat().st_mtime<SOURCE.stat().st_mtime:
            subprocess.run(['g++','-O3','-std=c++17','-shared','-fPIC',str(SOURCE),'-o',str(LIBRARY)],check=True)
        _lib=ctypes.CDLL(str(LIBRARY))
        _lib.cp_duplicate_score.argtypes=[ctypes.c_int]*5
        _lib.cp_duplicate_score.restype=ctypes.c_int
        _lib.cp_solve.argtypes=[ctypes.POINTER(ctypes.c_int)]+[ctypes.c_int]*6+[ctypes.c_uint32,ctypes.POINTER(ctypes.c_int),ctypes.POINTER(ctypes.c_uint64),ctypes.c_int,ctypes.POINTER(ctypes.c_int),ctypes.c_int]
        _lib.cp_solve.restype=ctypes.c_int
    return _lib

def score(level,strain,tricks,doubled=0,vulnerable=False):
    if not (1<=level<=7 and 0<=strain<=4 and 0<=tricks<=13 and 0<=doubled<=2):
        raise ValueError('invalid contract')
    return _library().cp_duplicate_score(level,strain,tricks,doubled,int(vulnerable))

def action_name(action):
    return {-1:'P',-2:'X',-3:'XX'}.get(action,str(action//5+1)+'CDHSN'[action%5])

def solve(dd_table,state=AuctionState(),vulnerability=2,want_pv=True,want_all=True):
    if len(dd_table)!=5 or any(len(row)!=4 for row in dd_table):
        raise ValueError('DD table must be 5 strains CDHSN by 4 seats NESW')
    values=[int(n) for row in dd_table for n in row]
    if any(n<0 or n>13 for n in values): raise ValueError('invalid DD tricks')
    if not (0<=state.bid<=34 and 0<=state.declarer<4 and 0<=state.doubled<=2 and 0<=state.passes<=2 and 0<=state.next_player<4):
        raise ValueError('invalid auction state')
    first=0
    for side in range(2):
        for strain in range(5):
            x=state.first_decl[side][strain]
            if x not in (0,1,2): raise ValueError('invalid first bidder')
            first |= x << (2*(side*5+strain))
    table=(ctypes.c_int*20)(*values)
    out=(ctypes.c_int*1024)()
    stats=(ctypes.c_uint64*4)()
    contracts=(ctypes.c_int*421)()
    lib=_library()
    start=time.perf_counter()
    status=lib.cp_solve(table,int(vulnerability),state.bid,state.declarer,state.doubled,state.passes,state.next_player,first,out,stats,int(want_pv),contracts,int(want_all))
    if status: raise RuntimeError('continuation solver failed')
    actions=list(out[5:5+out[4]])
    all_contracts=[]
    for identifier in contracts[1:contracts[0]+1]:
        bid=identifier//12
        declarer=(identifier%12)//3
        all_contracts.append({'level':bid//5+1,'strain':'CDHSN'[bid%5],
                              'declarer':'NESW'[declarer],'doubled':identifier%3})
    return {'score_ns':out[0], 'contract':{'level':out[1]//5+1,'strain':'CDHSN'[out[1]%5], 'declarer':'NESW'[out[2]],'doubled':out[3]} if want_pv else None,
            'optimal_contracts':all_contracts if want_all else None,
            'actions':actions,'auction':[action_name(a) for a in actions],
            'nodes':stats[0],'cache_hits':stats[1],'cache_entries':stats[2],
            'optimal_path_states':stats[3],
            'seconds':time.perf_counter()-start}
