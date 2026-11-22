#!/usr/bin/env python3
"""Compile the actual transformed setter and inject firmware write failures."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

spec = importlib.util.spec_from_file_location('charge_contract',
    Path(__file__).with_name('prepare_sheng_charge_error_contract.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
text = Path(sys.argv[1]).read_text()
updated = module.transform(text)
assert module.transform(updated) == updated
start = updated.index('static int battery_psy_set_prop(')
end = updated.index('\nstatic int battery_psy_prop_is_writeable(', start)
prefix = r'''
#include <assert.h>
#define EINVAL 22
#define PSY_TYPE_BATTERY 0
enum power_supply_property { POWER_SUPPLY_PROP_CHARGE_CONTROL_LIMIT,
    POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT, OTHER };
union power_supply_propval { int intval; };
struct power_supply { int unused; };
struct psy_state { int unused; };
struct battery_chg_dev { struct psy_state psy_list[1]; };
static struct battery_chg_dev device;
static int write_result, map_result;
static void *power_supply_get_drvdata(struct power_supply *p) { (void)p; return &device; }
static int get_property_id(struct psy_state *s, enum power_supply_property p) {
    (void)s; (void)p; return map_result;
}
static int battery_psy_set_charge_current(struct battery_chg_dev *d, int v) {
    (void)d; (void)v; return write_result;
}
static int battery_psy_set_fcc(struct battery_chg_dev *d, unsigned p, int v) {
    (void)d; (void)p; (void)v; return write_result;
}
'''
main = r'''
int main(void) {
    struct power_supply p; union power_supply_propval value = {1000000};
    for (int error = -110; error <= 0; error += 110) {
        write_result = error;
        assert(battery_psy_set_prop(&p, POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT, &value) == error);
        assert(battery_psy_set_prop(&p, POWER_SUPPLY_PROP_CHARGE_CONTROL_LIMIT, &value) == error);
    }
    assert(battery_psy_set_prop(&p, OTHER, &value) == -EINVAL);
    map_result = -19;
    assert(battery_psy_set_prop(&p, POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT, &value) == -19);
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='sheng-charge-error-') as folder:
    c, binary = Path(folder)/'test.c', Path(folder)/'test'
    c.write_text(prefix + updated[start:end] + main)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(c), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('PASS: actual setter propagates firmware timeout, success, invalid property and mapping errors')
