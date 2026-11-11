#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <limits>
#include <unordered_map>
#include <unordered_set>
#include <vector>

// Exact continuation auction minimax with a per-deal NS three-level no-double policy.
// Derived from continuation_par.cpp; the original solver remains unchanged.
// Seat order NESW, strains CDHSN, bids 0=1C ... 34=7NT.
namespace {
constexpr int INF = 30000;
struct State { uint32_t first; uint8_t bid, decl, dbl, passes, next; };

bool legal_action(const State &s, int action, uint32_t blocked_ns_level3_strains) {
  if(action==-1) return true;
  if(action==-2) {
    if(s.dbl || s.next%2==s.decl%2) return false;
    // Restrict only an EW double of an undoubled NS three-level suit contract.
    // The NT bit has no effect. The mask is fixed for this deal/search instance.
    if(s.bid/5==2 && s.bid%5<4 && s.decl%2==0 && s.next%2==1
       && (blocked_ns_level3_strains & (1u << (s.bid%5)))) return false;
    return true;
  }
  if(action==-3) return s.dbl==1 && s.next%2==s.decl%2;
  return action>s.bid && action<35;
}
struct Entry { int16_t value; uint8_t flag; int8_t move; }; // 0 exact,1 lower,2 upper
struct Move { int action; int estimate; }; // -1 pass, -2 double, -3 redouble

int duplicate_score(int level, int strain, int tricks, int dbl, bool vulnerable) {
  int need=level+6, mult=1<<dbl;
  if (tricks < need) {
    int down=need-tricks, loss;
    if (!dbl) loss=down*(vulnerable?100:50);
    else if(vulnerable) loss=200+(down-1)*300;
    else loss=100+std::min(down-1,2)*200+std::max(down-3,0)*300;
    if(dbl==2) loss*=2;
    return -loss;
  }
  int base=(strain<2?20:30)*level+(strain==4?10:0);
  int contract=base*mult, result=contract;
  result += contract>=100 ? (vulnerable?500:300) : 50;
  if (level==6) result += vulnerable?750:500;
  if (level==7) result += vulnerable?1500:1000;
  if (dbl) result += dbl==1?50:100;
  int over=tricks-need;
  result += over*(dbl ? (vulnerable?200:100)*(dbl==2?2:1) : (strain<2?20:30));
  return result;
}

class Solver {
public:
  int dd[5][4];
  int score[35][4][3];
  uint32_t relevant_mask[35];
  const uint32_t blocked_ns_level3_strains;
  uint64_t nodes=0, hits=0;
  std::unordered_map<uint64_t,Entry> cache;
  Solver(const int *table, int vul, uint32_t blocked)
      : blocked_ns_level3_strains(blocked & 15u) {
    std::memcpy(dd,table,sizeof(dd));
    uint32_t mask=0;
    for(int side=0;side<2;side++) for(int strain=0;strain<5;strain++) {
      if(dd[strain][side]!=dd[strain][side+2]) mask |= 3u << (2*(side*5+strain));
    }
    for(int bid=0;bid<35;bid++) {
      relevant_mask[bid]=mask;
      if(bid>=30) for(int side=0;side<2;side++) for(int strain=0;strain<=bid%5;strain++)
        relevant_mask[bid] &= ~(3u << (2*(side*5+strain)));
      for(int decl=0;decl<4;decl++) for(int dbl=0;dbl<3;dbl++)
        score[bid][decl][dbl] = (decl%2?-1:1)*duplicate_score(
          bid/5+1,bid%5,dd[bid%5][decl],dbl,(vul>>(decl%2))&1);
    }
    cache.reserve(65536);
  }
  uint64_t key(const State &s) const {
    return (uint64_t)(s.first & relevant_mask[s.bid])
      | ((uint64_t)s.bid<<20) | ((uint64_t)s.decl<<26)
      | ((uint64_t)s.dbl<<28) | ((uint64_t)s.passes<<30) | ((uint64_t)s.next<<32);
  }
  int terminal(const State &s) const { return score[s.bid][s.decl][s.dbl]; }
  bool legal(const State &s,int action) const {
    return legal_action(s,action,blocked_ns_level3_strains);
  }
  State child(State s,int action) const {
    int player=s.next;
    s.next=(s.next+1)%4;
    if(action==-1) { s.passes++; return s; }
    s.passes=0;
    if(action==-2) { s.dbl=1; return s; }
    if(action==-3) { s.dbl=2; return s; }
    int shift=2*((player%2)*5+action%5);
    int first=(s.first>>shift)&3;
    if(!first) { first=player/2+1; s.first|=first<<shift; }
    s.bid=action; s.dbl=0; s.decl=(first-1)*2+player%2;
    return s;
  }
  int estimate(const State &s,int action) const {
    State c=child(s,action);
    if(action<0) return terminal(c);
    int tricks=dd[c.bid%5][c.decl];
    int dbl=tricks < c.bid/5+7 ? 1 : 0;
    if(dbl && !legal(c,-2)) dbl=0; // Move ordering respects the same policy.
    return score[c.bid][c.decl][dbl];
  }
  int search(const State &s,int alpha,int beta) {
    nodes++;
    if(s.passes==3) return terminal(s);
    uint64_t k=key(s);
    int original_alpha=alpha,original_beta=beta,ttmove=-99;
    auto it=cache.find(k);
    if(it!=cache.end()) {
      hits++;
      auto e=it->second; ttmove=e.move;
      if(e.flag==0) return e.value;
      if(e.flag==1) alpha=std::max(alpha,(int)e.value);
      else beta=std::min(beta,(int)e.value);
      if(alpha>=beta) return e.value;
    }
    bool maximize=s.next%2==0;
    std::array<Move,38> moves; int count=0;
    moves[count++]={-1,estimate(s,-1)};
    if(legal(s,-2)) moves[count++]={-2,estimate(s,-2)};
    if(legal(s,-3)) moves[count++]={-3,estimate(s,-3)};
    for(int bid=s.bid+1;bid<35;bid++) moves[count++]={bid,estimate(s,bid)};
    std::stable_sort(moves.begin(),moves.begin()+count,[&](const Move&a,const Move&b){
      if(a.action==ttmove) return b.action!=ttmove;
      if(b.action==ttmove) return false;
      return maximize?a.estimate>b.estimate:a.estimate<b.estimate;
    });
    int best=maximize?-INF:INF,bestmove=-1;
    for(int i=0;i<count;i++) {
      int val=search(child(s,moves[i].action),alpha,beta);
      if((maximize&&val>best)||(!maximize&&val<best)) { best=val; bestmove=moves[i].action; }
      if(maximize) alpha=std::max(alpha,best); else beta=std::min(beta,best);
      if(alpha>=beta) break;
    }
    uint8_t flag=best<=original_alpha?2:best>=original_beta?1:0;
    cache[k]={(int16_t)best,flag,(int8_t)bestmove};
    return best;
  }
  std::vector<int> pv(State s,int value) {
    std::vector<int> result;
    // Prefer Pass among tied optimal moves for a stable, short representative.
    // At most nine calls per contract level/strain (two passes, X, two
    // passes, XX, then up to three passes); 512 exceeds the full-auction bound.
    while(s.passes<3 && result.size()<512) {
      std::vector<int> actions={-1};
      if(legal(s,-2)) actions.push_back(-2);
      if(legal(s,-3)) actions.push_back(-3);
      for(int bid=s.bid+1;bid<35;bid++) actions.push_back(bid);
      bool found=false;
      for(int action:actions) {
        auto c=child(s,action);
        int val=search(c,-INF,INF);
        if(val==value) { result.push_back(action); s=c; found=true; break; }
      }
      if(!found) return {};
    }
    return result;
  }
  void collect(const State &s,int target,int maximum_bid,uint32_t output_mask,
               std::unordered_set<uint64_t> &visited,std::array<bool,420> &found) {
    if(s.passes==3) {
      if(terminal(s)==target) found[s.bid*12+s.decl*3+s.dbl]=true;
      return;
    }
    // Preserve every first-bidder bit affecting either numeric values or a
    // possible target-score terminal identity. The remaining bits affect
    // neither legal moves, subtree values, nor reported contracts.
    uint32_t mask=relevant_mask[s.bid] | output_mask;
    uint64_t k=(uint64_t)(s.first & mask) | ((uint64_t)s.bid<<20)
      | ((uint64_t)s.decl<<26) | ((uint64_t)s.dbl<<28)
      | ((uint64_t)s.passes<<30) | ((uint64_t)s.next<<32);
    if(!visited.insert(k).second) return;
    std::vector<int> actions={-1};
    if(legal(s,-2)) actions.push_back(-2);
    if(legal(s,-3)) actions.push_back(-3);
    for(int bid=s.bid+1;bid<=maximum_bid;bid++) actions.push_back(bid);
    for(int action:actions) {
      State c=child(s,action);
      if(search(c,target-1,target+1)==target) collect(c,target,maximum_bid,output_mask,visited,found);
    }
  }
  std::vector<int> all_contracts(const State&s,int target,uint64_t&visited_count) {
    int maximum_bid=s.bid;
    uint32_t output_mask=0;
    for(int bid=s.bid;bid<35;bid++) for(int decl=0;decl<4;decl++) for(int dbl=0;dbl<3;dbl++)
      if(score[bid][decl][dbl]==target) {
        maximum_bid=std::max(maximum_bid,bid);
        output_mask |= 3u << (2*((decl%2)*5+bid%5));
      }
    std::array<bool,420> found{};
    std::unordered_set<uint64_t> visited;
    collect(s,target,maximum_bid,output_mask,visited,found);
    visited_count=visited.size();
    std::vector<int> result;
    for(int i=0;i<420;i++) if(found[i]) result.push_back(i);
    return result;
  }
};
}

extern "C" {
int cp_policy_is_legal(int bid,int decl,int doubled,int passes,int next,int action,int blocked_mask) {
  if(bid<0 || bid>34 || decl<0 || decl>3 || doubled<0 || doubled>2
     || passes<0 || passes>2 || next<0 || next>3 || blocked_mask<0 || blocked_mask>31) return 0;
  State s{0,(uint8_t)bid,(uint8_t)decl,(uint8_t)doubled,(uint8_t)passes,(uint8_t)next};
  return legal_action(s,action,(uint32_t)blocked_mask);
}
int cp_policy_duplicate_score(int level,int strain,int tricks,int doubled,int vulnerable) {
  return duplicate_score(level,strain,tricks,doubled,vulnerable);
}
// Output: value, terminal bid/decl/dbl, PV length, then actions.
// Caller supplies >=520 ints. stats: nodes,hits,cache size,optimal-path states.
int cp_policy_solve(const int *table,int vulnerable_mask,int blocked_mask,int bid,int decl,int doubled,
             int passes,int next,uint32_t first,int *out,uint64_t *stats,int want_pv,
             int *contracts_out,int want_all) {
  try {
    Solver solver(table,vulnerable_mask,(uint32_t)blocked_mask);
    State s{first,(uint8_t)bid,(uint8_t)decl,(uint8_t)doubled,(uint8_t)passes,(uint8_t)next};
    int value=solver.search(s,-INF,INF);
    auto line=want_pv?solver.pv(s,value):std::vector<int>{};
    State final=s; for(int action:line) final=solver.child(final,action);
    if(want_pv && final.passes!=3) return 2;
    out[0]=value; out[1]=final.bid; out[2]=final.decl; out[3]=final.dbl;
    out[4]=line.size(); for(size_t i=0;i<line.size();i++) out[5+i]=line[i];
    uint64_t visited_count=0;
    auto contracts=want_all?solver.all_contracts(s,value,visited_count):std::vector<int>{};
    contracts_out[0]=contracts.size();
    for(size_t i=0;i<contracts.size();i++) contracts_out[1+i]=contracts[i];
    stats[0]=solver.nodes;stats[1]=solver.hits;stats[2]=solver.cache.size();
    stats[3]=visited_count;
    return 0;
  } catch(...) {return 1;}
}
}
