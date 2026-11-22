# USB tethering, 2026-11-11

## Factory-source correction, 2026-11-15

The fallback classification below was incomplete. The original
OS3.0.303.0.WNXCNXM `vendor/etc/init/hw/init.qcom.usb.rc`, lines 172–177,
contains an explicit `on property:dev.bootcomplete=1 && property:ro.product.device=sheng`
action that changes `vendor.usb.rndis.func.name` from the shared vendor default
`gsi` to `rndis`. It also selects the RNDIS USB class/subclass/protocol. The
current board's actual FDT (DTBO index 48) has no `qcom,ipa` platform node;
loading the shared IPA modules cannot establish a binding there.

The device default `rndis` therefore preserves the shipping board's USB path.
Do not describe it as a repaired GSI path or enable another board's IPA node.
The Linux 6.18 Android fragment enables `CONFIG_USB_CONFIGFS_RNDIS` because
the reference kernel configuration did not supply the selected USB function.
That candidate still requires compilation and runtime verification.
Evidence: `reports/device/20261115-keyboard-indicator-release/ipa-current/`
and `usb-factory-path-audit.json` in that report directory's parent.

## Original diagnosis (historical)

The user reports that enabling USB tethering immediately reports failure and
turns itself off; Windows never creates a USB network adapter.

On ca10ede3 A, vendor.usb.rndis.func.name selects gsi. The gadget HAL rejects
functions=33 (RNDIS + ADB) with status=1 and falls back to ADB. Kernel logs show
gsi_bind: ipa is not ready, then ipa ready timeout and failed to start g1: -110.
Both gsi.rndis and the standard rndis.rndis already exist in gadget configfs.
The public QTI gadget HAL reads the function-name property for every request.

A temporary setprop to rndis allows the user's next enable attempt to succeed.
Tethering creates rndis0 and assigns 10.22.124.165/24; Windows creates Remote
NDIS Compatible Device and receives 10.22.124.239 by DHCP. The user confirms
working Internet access and says the later switch to photo transfer was manual.
No host network routing or adapter configuration was changed for the trial.

The device vendor.prop now selects rndis. This is a board configuration fallback
for the observed unavailable IPA path, using the already installed kernel USB
function; no public USB/kernel code changes or global tether-offload disabling.
The original GSI/IPA issue remains a separate limitation and is not claimed fixed.
Persistence across the combined image installation/reboot remains pending.

r48 installation and reboot completed on ca10ede3 A. The vendor partition and
declared vendor.prop output match the sealed image, and the property reads
rndis without a temporary setprop. The user confirmed that the switch stays
enabled, Windows creates the USB adapter, and Internet access works after
this reboot. The temporary RNDIS selection is now a permanent device default.

Reviewed references: piano seventeen 8c0bb4b9d15ea349eaa09d6de0aa4fec43f7ff41,
nuwa lineage-24.0 8e2b6ca4375919035587115189760eed64f14b8d, and sm8550-common
62f4b9c1d20c88f02e0bc7f1b2c932bd5c750eb1. Their board defaults retain GSI;
they do not override the actual sheng failure evidence. QTI's manifest-pinned
vendor/qcom/opensource/usb at 0d32cd0034b767aa8a6b5fbc8516570af8cf3e5f
supports the standard rndis selection and uses it
as a board default on other platforms; their board identity is not copied.
