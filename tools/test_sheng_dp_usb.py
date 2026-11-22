#!/usr/bin/env python3
"""Exercise the actual legacy-PLL allocation/unwind code under ASan and UBSan."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from prepare_sheng_dp_usb import prepare, PLL


def function(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root', type=Path, required=True)
args = parser.parse_args()
prepare(args.source_root, check=True)
source = (args.source_root / PLL / 'dp_pll.c').read_text()
clock = (args.source_root / PLL / 'dp_pll_4nm.c').read_text()
harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#define GFP_KERNEL 0
#define DP_PLL_NUM_CLKS 2
#define DP_PLL_4NM_V1_1 4
#define ERR_PTR(n) ((void *)(intptr_t)(n))
#define IS_ERR_OR_NULL(p) (!(p) || (intptr_t)(p) < 0)
#define DP_INFO(...) ((void)0)
struct device_node { int unused; } root_node, node;
static struct device_node *of_root = &root_node;
struct device { struct device_node *of_node; };
struct platform_device { struct device dev; } pdev = {{&node}};
struct clk_onecell_data { void **clks; };
struct dp_pll {
    struct platform_device *pdev;
    void *parser, *aux;
    unsigned dp_core_revision, revision;
    const char *name;
    bool legacy_owner, clock_provider_registered, ssc_en, bonding_en;
    struct clk_onecell_data *clk_data;
};
struct dp_pll_in { struct platform_device *pdev; void *parser, *aux; unsigned dp_core_revision; };
static int is_sheng = 1, cells = 1, fail_alloc, fail_io, fail_clocks;
static int frees, clocks_removed, providers_removed;
static const char *revision = "4nm-v1.1";
static int of_property_match_string(void *n, const char *p, const char *v) { return is_sheng ? 0 : -1; }
static int of_property_read_string(void *n, const char *p, const char **v) { *v = revision; return 0; }
static int of_property_present(void *n, const char *p) { return cells; }
static int of_property_read_bool(void *n, const char *p) { return 0; }
static void *kzalloc(size_t n, int flags) { return fail_alloc ? NULL : calloc(1, n); }
static void kfree(void *p) { if (p) frees++; free(p); }
static void clk_unregister(void *p) { clocks_removed++; }
static void of_clk_del_provider(void *p) { providers_removed++; }
static int dp_pll_fill_io(struct dp_pll *pll) { return fail_io ? -ENOMEM : 0; }
static int dp_pll_clock_register_4nm(struct dp_pll *pll) {
    if (fail_clocks) return -EINVAL;
    pll->clk_data = calloc(1, sizeof(*pll->clk_data));
    pll->clk_data->clks = calloc(2, sizeof(void *));
    pll->clk_data->clks[0] = (void *)1;
    pll->clk_data->clks[1] = (void *)2;
    pll->clock_provider_registered = true;
    return 0;
}
'''
harness += function(clock, 'void dp_pll_clock_unregister_4nm(')
harness += function(source, 'static struct dp_pll *dp_pll_get_sheng_legacy(')
harness += function(source, 'void dp_pll_put(')
harness += r'''
int main(void) {
    struct dp_pll_in in = {&pdev, (void *)3, (void *)4, 0x500};
    struct dp_pll *pll;
    is_sheng = 0; assert(dp_pll_get_sheng_legacy(&in) == ERR_PTR(-EINVAL));
    is_sheng = 1; revision = "3nm-v1"; assert(dp_pll_get_sheng_legacy(&in) == ERR_PTR(-EINVAL));
    revision = "4nm-v1.1"; cells = 0; assert(dp_pll_get_sheng_legacy(&in) == ERR_PTR(-EINVAL));
    cells = 1; fail_alloc = 1; assert(dp_pll_get_sheng_legacy(&in) == ERR_PTR(-ENOMEM));
    fail_alloc = 0; fail_io = 1; assert(dp_pll_get_sheng_legacy(&in) == ERR_PTR(-ENOMEM)); assert(frees == 1);
    fail_io = 0; fail_clocks = 1; assert(dp_pll_get_sheng_legacy(&in) == ERR_PTR(-EINVAL)); assert(frees == 2);
    fail_clocks = 0; pll = dp_pll_get_sheng_legacy(&in); assert(!IS_ERR_OR_NULL(pll));
    assert(pll->parser == in.parser && pll->aux == in.aux && pll->dp_core_revision == in.dp_core_revision);
    dp_pll_put(pll); assert(clocks_removed == 2 && providers_removed == 1 && frees == 5);
    dp_pll_put(NULL); dp_pll_put(ERR_PTR(-EINVAL));
    /* A separately probed PLL retains its independent lifetime. */
    pll = calloc(1, sizeof(*pll)); dp_pll_put(pll); assert(frees == 5); free(pll);
    /* Partially registered clocks must unwind without touching a provider. */
    pll = calloc(1, sizeof(*pll)); pll->pdev = &pdev;
    pll->clk_data = calloc(1, sizeof(*pll->clk_data));
    pll->clk_data->clks = calloc(2, sizeof(void *)); pll->clk_data->clks[0] = (void *)1;
    dp_pll_clock_unregister_4nm(pll); dp_pll_clock_unregister_4nm(pll);
    assert(clocks_removed == 3 && providers_removed == 1); free(pll);
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='sheng-dp-usb-') as temporary:
    path = Path(temporary)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
print('PASS: legacy PLL gating, allocation failures, clock cleanup, independent modern lifetime; ASan/UBSan')
