/* SPDX-License-Identifier: GPL-2.0-only */
/* Shipping cnss2: platform comes from hwid.project, country from hwid_value. */
static const char *sheng_wifi_bdf_name(u32 platform, u32 country)
{
	switch (platform) {
	case 1: return country == 1 ? "bd_m2gl.elf" : "bd_m2.elf";
	case 2: return country == 1 ? "bd_m3gl.elf" : "bd_m3.elf";
	case 3: return "bdwlan.elf";
	case 4: return country == 1 ? "bd_m11gl.elf" : "bd_m11.elf";
	case 5: return country == 1 ? "bd_m1gl.elf" : "bd_m1.elf";
	case 6: return country == 1 ? "bd_m18gl.elf" : "bd_m18.elf";
	case 7: return country ? "bd_n11gl.elf" : "bd_n11.elf";
	case 8: return country ? "bd_n81agl.elf" : "bd_n81a.elf";
	default: return NULL;
	}
}
