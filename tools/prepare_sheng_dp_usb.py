#!/usr/bin/env python3
"""Apply the device-owned legacy DP PLL and USB PHY clock compatibility fixes."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path

PLL = 'vendor/qcom/opensource/display-drivers/msm/dp/'
LT_VALUES = (Path(__file__).resolve().parents[1] /
             'interfaces/kernel/6.18/sheng_dp_legacy_lt.h').read_text()
LEGACY = '''static struct dp_pll *dp_pll_get_sheng_legacy(struct dp_pll_in *in)
{
	struct device_node *node = in->pdev->dev.of_node;
	struct dp_pll *pll;
	const char *revision;
	int rc;

	/* Shipping sheng DT embeds the PLL clocks in the display node. */
	if (!of_root || of_property_match_string(of_root, "model",
			"Qualcomm Technologies, Inc. 8550 sheng") < 0 ||
			of_property_read_string(node, "qcom,pll-revision", &revision) ||
			strcmp(revision, "4nm-v1.1") ||
			!of_property_present(node, "#clock-cells"))
		return ERR_PTR(-EINVAL);

	pll = kzalloc(sizeof(*pll), GFP_KERNEL);
	if (!pll)
		return ERR_PTR(-ENOMEM);
	pll->pdev = in->pdev;
	pll->parser = in->parser;
	pll->aux = in->aux;
	pll->dp_core_revision = in->dp_core_revision;
	pll->revision = DP_PLL_4NM_V1_1;
	pll->name = "dp0";
	pll->legacy_owner = true;
	pll->ssc_en = of_property_read_bool(node, "qcom,ssc-feature-enable");
	pll->bonding_en = of_property_read_bool(node, "qcom,bonding-feature-enable");
	rc = dp_pll_fill_io(pll);
	if (rc)
		goto error;
	rc = dp_pll_clock_register_4nm(pll);
	if (rc)
		goto error;
	DP_INFO("sheng legacy DP PLL 4nm-v1.1 clocks registered\\n");
	return pll;
error:
	kfree(pll);
	return ERR_PTR(rc);
}

'''

CHANGES = {
    PLL + 'dp_catalog_v420.c': [
        ('struct dp_catalog_private_v420 {',
         LT_VALUES + '\nstruct dp_catalog_private_v420 {'),
        ('\t} else {\n\t\tvalue0 = vm_voltage_swing[v_level][p_level];',
         '\t} else if (sheng_dp_legacy_lt_values(version, phy_version,\n'
         '\t\t\tv_level, p_level, high, &value0, &value1)) {\n'
         '\t\t/* Keep shipping PHY tuning when the legacy DT has no tables. */\n'
         '\t} else {\n\t\tvalue0 = vm_voltage_swing[v_level][p_level];'),
    ],
    PLL + 'dp_ctrl.c': [
        ('drm_dp_dpcd_read_link_status(ctrl->aux->drm_aux, link_status)',
         'drm_dp_dpcd_read(ctrl->aux->drm_aux, DP_LANE0_1_STATUS,\n'
         '\t\t\tlink_status, DP_LINK_STATUS_SIZE)'),
        ('#include "dp_ctrl.h"', '#include <linux/of.h>\n#include "dp_ctrl.h"'),
        ('static int dp_ctrl_link_rate_down_shift(struct dp_ctrl_private *ctrl)\n{\n\tint ret = 0;',
         'static int dp_ctrl_link_rate_down_shift(struct dp_ctrl_private *ctrl)\n{\n'
         '\tint ret = 0;\n\tu8 old_bw_code;'),
        ('\tswitch (ctrl->link->link_params.bw_code) {',
         '\told_bw_code = ctrl->link->link_params.bw_code;\n'
         '\tswitch (ctrl->link->link_params.bw_code) {'),
        ('\tDP_DEBUG("new bw code=0x%x\\n", ctrl->link->link_params.bw_code);',
         '\t/* Retry all negotiated lanes at the lower rate before losing bandwidth.\n'
         '\t * EQ failure at HBR2 may have reduced two lanes to one already.\n'
         '\t */\n'
         '\tif (ctrl->link->link_params.bw_code < old_bw_code &&\n'
         '\t\t\tctrl->link->link_params.lane_count < ctrl->initial_lane_count &&\n'
         '\t\t\tof_root && of_property_match_string(of_root, "model",\n'
         '\t\t\t"Qualcomm Technologies, Inc. 8550 sheng") >= 0)\n'
         '\t\tctrl->link->link_params.lane_count = ctrl->initial_lane_count;\n\n'
         '\tDP_DEBUG("new bw code=0x%x\\n", ctrl->link->link_params.bw_code);'),
        ('\tcatalog->phy_lane_cfg(catalog, ctrl->orientation,\n'
         '\t\t\t\tlink_params->lane_count);\n\n',
         '\t/* Lane metadata is refreshed inside the retry loop below. */\n\n'),
        ('\t\trc = dp_ctrl_enable_link_clock(ctrl);',
         '\t\t/* The PLL consumes this metadata on every rate/lane retry. */\n'
         '\t\tcatalog->phy_lane_cfg(catalog, ctrl->orientation,\n'
         '\t\t\t\tlink_params->lane_count);\n\n'
         '\t\trc = dp_ctrl_enable_link_clock(ctrl);'),
    ],
    PLL + 'dp_link.c': [
        ('drm_dp_dpcd_read_link_status(link->aux->drm_aux,\n\t\tlink->link_status)',
         'drm_dp_dpcd_read(link->aux->drm_aux, DP_LANE0_1_STATUS,\n'
         '\t\tlink->link_status, DP_LINK_STATUS_SIZE)'),
    ],
    PLL + 'dp_pll.h': [
        ('\tbool ssc_en;\n\tbool bonding_en;',
         '\tbool ssc_en;\n\tbool bonding_en;\n\tbool legacy_owner;\n\tbool clock_provider_registered;'),
    ],
    PLL + 'dp_pll.c': [
        ('struct dp_pll *dp_pll_get(struct dp_pll_in *in)\n',
         LEGACY + 'struct dp_pll *dp_pll_get(struct dp_pll_in *in)\n'),
        ('\tif (!node) {\n\t\tDP_ERR("couldn\'t find dp-pll node\\n");\n\t\treturn ERR_PTR(-EINVAL);\n\t}',
         '\tif (!node)\n\t\treturn dp_pll_get_sheng_legacy(in);'),
        ('\tpdev = of_find_device_by_node(node);\n',
         '\tpdev = of_find_device_by_node(node);\n\tof_node_put(node);\n'),
        ('\t\treturn ERR_PTR(-ENODEV);\n\t}\n\n\tpll = platform_get_drvdata(pdev);',
         '\t\treturn ERR_PTR(-EPROBE_DEFER);\n\t}\n\n\tpll = platform_get_drvdata(pdev);'),
        ('\tpll = platform_get_drvdata(pdev);\n\tif (!pll)',
         '\tpll = platform_get_drvdata(pdev);\n\tput_device(&pdev->dev);\n\tif (!pll)'),
        ('\t\tDP_ERR("couldn\'t find pll\\n");\n\t\treturn ERR_PTR(-ENODEV);',
         '\t\tDP_ERR("couldn\'t find pll\\n");\n\t\treturn ERR_PTR(-EPROBE_DEFER);'),
        ('void dp_pll_put(struct dp_pll *pll)\n{\n}',
         'void dp_pll_put(struct dp_pll *pll)\n{\n'
         '\tif (!IS_ERR_OR_NULL(pll) && pll->legacy_owner) {\n'
         '\t\tdp_pll_clock_unregister_4nm(pll);\n\t\tkfree(pll);\n\t}\n}'),
    ],
    PLL + 'dp_pll_4nm.c': [
        ('\tDP_DEBUG("success\\n");\n\treturn rc;\n\nclk_reg_fail:',
         '\tpll->clock_provider_registered = true;\n\tDP_DEBUG("success\\n");\n\treturn rc;\n\nclk_reg_fail:'),
        ('void dp_pll_clock_unregister_4nm(struct dp_pll *pll)\n{\n'
         '\tkfree(pll->clk_data->clks);\n\tkfree(pll->clk_data);\n}',
         'void dp_pll_clock_unregister_4nm(struct dp_pll *pll)\n{\n\tint i;\n\n'
         '\tif (!pll->clk_data)\n\t\treturn;\n'
         '\tif (pll->clock_provider_registered) {\n'
         '\t\tof_clk_del_provider(pll->pdev->dev.of_node);\n'
         '\t\tpll->clock_provider_registered = false;\n\t}\n'
         '\tfor (i = DP_PLL_NUM_CLKS - 1; i >= 0; i--)\n'
         '\t\tif (!IS_ERR_OR_NULL(pll->clk_data->clks[i]))\n'
         '\t\t\tclk_unregister(pll->clk_data->clks[i]);\n'
         '\tkfree(pll->clk_data->clks);\n\tkfree(pll->clk_data);\n'
         '\tpll->clk_data = NULL;\n}'),
    ],
    'soc/drivers/usb/phy/phy-msm-ssusb-qmp.c': [
        ('static int sheng_ssphy_qmp_get_pipe_xo(struct msm_ssphy_qmp *phy,',
         'static void sheng_ssphy_put_pipe_xo(void *clock)\n{\n\tclk_put(clock);\n}\n\n'
         'static int sheng_ssphy_qmp_get_pipe_xo(struct msm_ssphy_qmp *phy,'),
        ('\tphy->pipe_clk_xo = devm_clk_hw_get_clk(dev, xo, "pipe_clk_xo");',
         '\t/* XO belongs to GCC, so manage this consumer reference explicitly. */\n'
         '\tphy->pipe_clk_xo = clk_hw_get_clk(xo, "pipe_clk_xo");'),
        ('\tdev_info(dev, "sheng pipe suspend parent: %s\\n", clk_hw_get_name(xo));\n\treturn 0;',
         '\tdev_info(dev, "sheng pipe suspend parent: %s\\n", clk_hw_get_name(xo));\n'
         '\treturn devm_add_action_or_reset(dev, sheng_ssphy_put_pipe_xo, phy->pipe_clk_xo);'),
    ],
}


def prepare(root, check=False, emit_patch=None):
    prepared, receipt, patch = {}, {}, []
    for name, replacements in CHANGES.items():
        path = root / name
        before = path.read_text()
        after = before
        for old, new in replacements:
            if after.count(new) == 1:
                continue
            if after.count(old) != 1:
                raise ValueError('Unexpected source for ' + name + ': ' + old[:80])
            after = after.replace(old, new, 1)
        prepared[path] = after
        receipt[name] = {'before': hashlib.sha256(before.encode()).hexdigest(),
                         'after': hashlib.sha256(after.encode()).hexdigest()}
        patch.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                     fromfile='a/' + name, tofile='b/' + name))
        if check and before != after:
            raise ValueError('Fix not applied: ' + name)
    if not check:
        for path, after in prepared.items():
            if path.read_text() != after:
                path.write_text(after)
    if emit_patch:
        emit_patch.write_text(''.join(patch))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True, help='Prepared k618 directory')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--emit-patch', type=Path)
    args = parser.parse_args()
    result = prepare(args.source_root.resolve(), args.check, args.emit_patch)
    if args.report:
        args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
