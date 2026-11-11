// 續叫 Par 搜尋（保留叫序）：雙方全資訊、以 DD 墩數表為準的 minimax，南北取最大。
// 輸入（stdin，每行一副）：
//   id t[20] nsLen[4] ewMax[4] protMask start...
//   t 依王牌 C D H S N（各 4 個座位 N E S W）；nsLen/ewMax 依 C D H S。
//   protMask：bit k 表示 ewMax==k 時保護（3=3-2, 4=4-1）。0 = 原始模型。
//   start: bid decl dbl passes toAct first[10]（first[side*5+strain]，-1 = 無）
// 輸出：id value nOutcomes outcome;outcome;... | path
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <set>
#include <tuple>
#include <unordered_map>
#include <unordered_set>
#include <algorithm>
#include <cstdlib>
using namespace std;

static int T[5][4];          // tricks[strain][seat]
static int nsLen[4], ewMax[4], protMask, maxBid = 34, collapse = 1;
static const bool VUL[2] = {false, true};  // side 0 = NS 無身價，side 1 = EW 有身價

static int score_decl(int bid, int dbl, int tricks, bool vul) {  // 莊家方得分
    int level = bid / 5 + 1, strain = bid % 5, need = level + 6;
    if (tricks >= need) {
        int per = (strain <= 1) ? 20 : 30;
        int ts = (strain == 4) ? 40 + 30 * (level - 1) : per * level;
        int mult = dbl == 0 ? 1 : dbl == 1 ? 2 : 4;
        ts *= mult;
        int s = ts;
        s += ts >= 100 ? (vul ? 500 : 300) : 50;
        if (level == 6) s += vul ? 750 : 500;
        if (level == 7) s += vul ? 1500 : 1000;
        int over = tricks - need;
        if (dbl == 0) s += over * (strain == 4 ? 30 : per);
        else s += over * (vul ? 200 : 100) * (dbl == 2 ? 2 : 1);
        if (dbl) s += dbl == 1 ? 50 : 100;
        return s;
    }
    int down = need - tricks, s;
    if (dbl == 0) s = down * (vul ? 100 : 50);
    else {
        if (vul) s = 200 + 300 * (down - 1);
        else s = down <= 1 ? 100 : down <= 3 ? 100 + 200 * (down - 1) : 500 + 300 * (down - 3);
        if (dbl == 2) s *= 2;
    }
    return -s;
}
static int score_ns(int bid, int decl, int dbl) {
    int side = decl & 1;
    int s = score_decl(bid, dbl, T[bid % 5][decl], VUL[side]);
    return side == 0 ? s : -s;
}

struct St { int bid, decl, dbl, passes, toAct; int8_t first[10]; };
static bool same(int strain, int seat) { return T[strain][seat] == T[strain][(seat + 2) & 3]; }
static uint64_t key_true(const St& s) {
    uint64_t k = s.bid; k = k * 4 + s.decl; k = k * 3 + s.dbl; k = k * 3 + s.passes; k = k * 4 + s.toAct;
    for (int i = 0; i < 10; i++) k = k * 5 + (s.first[i] + 1);
    return k;
}
// 值的快取鍵：同方兩家作莊墩數相同的王牌，誰先叫不影響任何分數，從鍵中去掉；莊家取代表座位
static uint64_t key(const St& s) {
    if (!collapse) return key_true(s);
    St c = s;
    if (same(s.bid % 5, s.decl)) c.decl = s.decl & 1;
    for (int i = 0; i < 10; i++) if (same(i % 5, i / 5)) c.first[i] = -1;
    return key_true(c);
}
static unordered_map<uint64_t, int> memo;
static long nodes;

static bool protectedX(const St& s) {  // 東西不可賭倍
    if (!protMask) return false;
    if ((s.decl & 1) != 0) return false;           // 合約須為南北
    int level = s.bid / 5 + 1, strain = s.bid % 5;
    if (level != 3 || strain == 4) return false;
    if (nsLen[strain] != 8) return false;
    return (protMask >> ewMax[strain]) & 1;
}

// 合法叫品：-1 Pass, -2 X, -3 XX, >=0 bid
static void moves(const St& s, vector<int>& mv) {
    mv.clear(); mv.push_back(-1);
    int side = s.toAct & 1, dside = s.decl & 1;
    if (s.dbl == 0 && dside != side && !(side == 1 && protectedX(s))) mv.push_back(-2);
    if (s.dbl == 1 && dside == side) mv.push_back(-3);
    for (int b = s.bid + 1; b <= maxBid; b++) mv.push_back(b);
}
static bool apply(const St& s, int m, St& n) {  // 回傳 true 表示叫牌結束
    n = s; n.toAct = (s.toAct + 1) & 3;
    if (m == -1) { n.passes++; return n.passes == 3; }
    n.passes = 0;
    if (m == -2) { n.dbl = 1; return false; }
    if (m == -3) { n.dbl = 2; return false; }
    int side = s.toAct & 1, strain = m % 5;
    int8_t& fs = n.first[side * 5 + strain];
    if (fs < 0) fs = s.toAct;   // 一律記錄真正的第一叫者
    int decl = fs;
    n.bid = m; n.decl = decl; n.dbl = 0;
    return false;
}
static int solve(const St& s) {
    uint64_t k = key(s);
    auto it = memo.find(k);
    if (it != memo.end()) return it->second;
    nodes++;
    bool ns = (s.toAct & 1) == 0;
    int best = ns ? -1000000 : 1000000;
    vector<int> mv; moves(s, mv);
    for (int m : mv) {
        St n; int v;
        if (apply(s, m, n)) v = score_ns(n.bid, n.decl, n.dbl);
        else v = solve(n);
        if (ns ? v > best : v < best) best = v;
    }
    memo[k] = best;
    return best;
}
static const char* SN = "CDHSN";
static const char* SEAT = "NESW";
static string callstr(int m) {
    if (m == -1) return "P"; if (m == -2) return "X"; if (m == -3) return "XX";
    return to_string(m / 5 + 1) + SN[m % 5];
}
static string outstr(const St& s, bool collapsedDecl) {
    string r = to_string(s.bid / 5 + 1) + SN[s.bid % 5];
    if (s.dbl == 1) r += "X"; if (s.dbl == 2) r += "XX";
    r += "-";
    if (collapsedDecl) { int a = min(s.decl, (s.decl + 2) & 3); r += SEAT[a]; r += "/"; r += SEAT[a + 2]; }
    else r += SEAT[s.decl];
    return r;
}
// 收集所有最佳終局（兩方在每個節點走任一最佳叫品）
static unordered_set<uint64_t> visited;
static set<string> outs;
static void collect(const St& s) {
    uint64_t k = key_true(s);
    if (!visited.insert(k).second) return;
    int val = solve(s);
    vector<int> mv; moves(s, mv);
    for (int m : mv) {
        St n;
        if (apply(s, m, n)) {
            if (score_ns(n.bid, n.decl, n.dbl) == val) {
                int strain = n.bid % 5, p = (n.decl + 2) & 3;
                outs.insert(outstr(n, false)); (void)strain; (void)p;
            }
        } else if (solve(n) == val) collect(n);
    }
}
int main(int argc, char** argv) {
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--nocollapse")) collapse = 0;
        if (!strcmp(argv[i], "--maxbid")) maxBid = atoi(argv[++i]);
    }
    char id[64];
    while (scanf("%63s", id) == 1) {
        int t[20];
        for (int st = 0; st < 5; st++) for (int h = 0; h < 4; h++) scanf("%d", &T[st][h]);
        for (int i = 0; i < 4; i++) scanf("%d", &nsLen[i]);
        for (int i = 0; i < 4; i++) scanf("%d", &ewMax[i]);
        scanf("%d", &protMask);
        St s; int f;
        scanf("%d %d %d %d %d", &s.bid, &s.decl, &s.dbl, &s.passes, &s.toAct);
        for (int i = 0; i < 10; i++) { scanf("%d", &f); s.first[i] = f; }
        memo.clear(); visited.clear(); outs.clear(); nodes = 0;
        int v = solve(s);
        collect(s);
        // 代表路徑：每步取第一個最佳叫品（Pass、X、XX、低叫品優先）
        string path; St c = s;
        while (true) {
            int val = solve(c); vector<int> mv; moves(c, mv); bool done = false;
            for (int m : mv) {
                St n; bool end = apply(c, m, n);
                int w = end ? score_ns(n.bid, n.decl, n.dbl) : solve(n);
                if (w == val) { path += callstr(m) + " "; c = n; done = end; break; }
            }
            if (done) break;
        }
        printf("%s %d %zu ", id, v, outs.size());
        bool firstOut = true;
        for (auto& o : outs) { printf(firstOut ? "%s" : ";%s", o.c_str()); firstOut = false; }
        printf(" | %s| %s %ld\n", path.c_str(), outstr(c, false).c_str(), nodes);
        fflush(stdout);
    }
}
