/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after sheng_qti_pogo_api.h in the sheng QTI charger driver. */
int sheng_usb_get_cc_orientation(int *orientation);

int sheng_usb_get_cc_orientation(int *orientation)
{
	struct sheng_pogo_request request = {
		.opcode = SHENG_POGO_GET,
		.property = XM_PROP_CC_ORIENTATION,
	};
	u32 value;
	int ret;

	if (!orientation)
		return -EINVAL;
	if (!of_root || of_property_match_string(of_root, "model",
			"Qualcomm Technologies, Inc. 8550 sheng") < 0)
		return -ENODEV;
	/* This owner is published only for the verified sheng panel identity.
	 * Removal takes the same lock before releasing the GLINK transport.
	 */
	mutex_lock(&sheng_keyboard_charger_lock);
	ret = sheng_keyboard_bcdev ?
		sheng_pogo_transfer(sheng_keyboard_bcdev, &request, 0, &value) :
		-ENODEV;
	if (!ret) {
		/* Never reuse a cached pre-disconnect direction or guess CC2. */
		if (value == 1 || value == 2)
			*orientation = value;
		else
			ret = value == 0 ? -ENODATA : -EPROTO;
	}
	mutex_unlock(&sheng_keyboard_charger_lock);
	return ret;
}
EXPORT_SYMBOL_GPL(sheng_usb_get_cc_orientation);
