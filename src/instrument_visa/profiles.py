from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceProfile:
    manufacturer: str
    model_family: str
    device_type: str
    key: str = "unknown"
    supports_scope_measurements: bool = False
    supports_waveform: bool = False
    supports_dmm_read: bool = False
    supports_screenshot: bool = False
    supports_sparameters: bool = False
    supports_signal_generator: bool = False
    supports_power_supply: bool = False


UNKNOWN_PROFILE = DeviceProfile(
    manufacturer="Unbekannt",
    model_family="Unbekannt",
    device_type="Unbekannt",
    key="unknown",
    supports_scope_measurements=True,
    supports_waveform=True,
    supports_dmm_read=True,
    supports_screenshot=True,
    supports_sparameters=True,
)


def detect_profile(idn: str) -> DeviceProfile:
    normalized = idn.upper()
    compact = _compact_idn(idn)

    if any(model in compact for model in ("DSOX", "MSOX")):
        return DeviceProfile(
            manufacturer="Keysight/Agilent",
            model_family="InfiniiVision X-Series",
            device_type="Oszilloskop",
            key="keysight_infinivision_x",
            supports_scope_measurements=True,
            supports_waveform=True,
            supports_screenshot=True,
        )

    if any(model in compact for model in ("MSO6", "DSO6")):
        return DeviceProfile(
            manufacturer="Keysight/Agilent",
            model_family="InfiniiVision 6000",
            device_type="Oszilloskop",
            key="keysight_infinivision_6000",
            supports_scope_measurements=True,
            supports_waveform=True,
            supports_screenshot=True,
        )

    if "MSO7" in compact or "DSO7" in compact:
        return DeviceProfile(
            manufacturer="Keysight/Agilent",
            model_family="InfiniiVision 7000",
            device_type="Oszilloskop",
            key="keysight_infinivision_7000",
            supports_scope_measurements=True,
            supports_waveform=True,
            supports_screenshot=True,
        )

    if "54622D" in compact or "5462" in compact:
        return DeviceProfile(
            manufacturer="HP/Agilent",
            model_family="54600/54620",
            device_type="Oszilloskop",
            key="agilent_54600",
            supports_scope_measurements=True,
            supports_waveform=True,
            supports_screenshot=True,
        )

    if "TEKTRONIX" in compact and any(device in compact for device in ("MSO4", "MDO4", "MDO3", "DPO4")):
        return DeviceProfile(
            manufacturer="Tektronix",
            model_family="MDO/MSO/DPO",
            device_type="Oszilloskop",
            key="tektronix_mdo",
            supports_scope_measurements=True,
            supports_screenshot=True,
        )

    if "TEKTRONIX" in compact and ("TDS420" in compact or "TDS4" in compact):
        return DeviceProfile(
            manufacturer="Tektronix",
            model_family="TDS400",
            device_type="Oszilloskop",
            key="tektronix_tds400",
            supports_scope_measurements=True,
            supports_waveform=True,
            supports_screenshot=True,
        )

    if "TEKTRONIX" in compact and "TDS30" in compact:
        return DeviceProfile(
            manufacturer="Tektronix",
            model_family="TDS3000",
            device_type="Oszilloskop",
            key="tektronix_tds30",
            supports_scope_measurements=True,
            supports_screenshot=True,
        )

    if "4395A" in compact:
        return DeviceProfile(
            manufacturer="HP/Agilent",
            model_family="4395A",
            device_type="Netzwerk-/Spektrumanalysator",
            key="hp_4395a",
            supports_waveform=True,
        )

    if "8591A" in compact:
        return DeviceProfile(
            manufacturer="HP",
            model_family="8591A",
            device_type="Spektrumanalysator",
            key="hp_8591a",
            supports_waveform=True,
            supports_screenshot=True,
        )

    if "KEITHLEY" in compact and "2000" in compact:
        return DeviceProfile(
            manufacturer="Keithley",
            model_family="2000",
            device_type="Multimeter",
            key="keithley_2000",
            supports_dmm_read=True,
        )

    if "34970A" in compact or "34972A" in compact or "HP34970" in compact or "HEWLETTPACKARD34970" in compact:
        return DeviceProfile(
            manufacturer="Keysight/Agilent/HP",
            model_family="34970A/34972A",
            device_type="Datenlogger",
            key="keysight_34970a",
        )

    if "PICOSCOPE" in compact:
        return DeviceProfile(
            manufacturer="Pico Technology",
            model_family="PicoScope",
            device_type="PicoScope",
            key="picoscope",
        )

    if "SALEAE" in compact or "LOGIC2AUTOMATION" in compact:
        return DeviceProfile(
            manufacturer="Saleae",
            model_family="Logic 2 Automation",
            device_type="Saleae",
            key="saleae_logic2",
        )

    if ("KONICAMINOLTA" in compact or "KONICA" in compact) and "CA410" in compact:
        return DeviceProfile(
            manufacturer="Konica Minolta",
            model_family="CA-410",
            device_type="Farbmessgerät",
            key="konica_minolta_ca410",
        )

    if "344" in compact or "L44" in compact:
        return DeviceProfile(
            manufacturer="Keysight/Agilent",
            model_family="344xx/L44xx",
            device_type="Multimeter",
            key="keysight_344_l44",
            supports_dmm_read=True,
        )

    if "E5071C" in compact:
        return DeviceProfile(
            manufacturer="Keysight/Agilent",
            model_family="E5071C",
            device_type="Netzwerkanalysator",
            key="keysight_e5071c",
            supports_screenshot=True,
            supports_sparameters=True,
        )

    if "FSW" in compact:
        return DeviceProfile(
            manufacturer="Rohde & Schwarz",
            model_family="FSW",
            device_type="Spektrumanalysator",
            key="rs_fsw",
            supports_screenshot=True,
        )

    if "E4402B" in compact:
        return DeviceProfile(
            manufacturer="HP/Agilent",
            model_family="E4402B ESA",
            device_type="Spektrumanalysator",
            key="hp_agilent_e4402b",
            supports_screenshot=True,
            supports_waveform=True,
        )

    if "E740" in compact:
        return DeviceProfile(
            manufacturer="HP/Agilent",
            model_family="E740",
            device_type="Spektrumanalysator",
            key="hp_e740",
            supports_screenshot=True,
            supports_waveform=True,
        )

    if "ROHDE" in compact and any(model in compact for model in ("SMGU", "SMHU")):
        return DeviceProfile(
            manufacturer="Rohde & Schwarz",
            model_family="SMGU/SMHU",
            device_type="Signalgenerator",
            key="rs_smg_legacy",
            supports_signal_generator=True,
        )

    if "ROHDE" in compact and any(model in compact for model in ("SME", "SMT", "SMIQ")):
        return DeviceProfile(
            manufacturer="Rohde & Schwarz",
            model_family="SME/SMT/SMIQ",
            device_type="Signalgenerator",
            key="rs_sme_smt_smiq",
            supports_signal_generator=True,
        )

    if ("HAMEG" in compact or "ROHDE" in compact) and "HMS" in compact:
        return DeviceProfile(
            manufacturer="Rohde & Schwarz / Hameg",
            model_family="HMS-X",
            device_type="Spektrumanalysator",
            key="rs_hameg_hms",
            supports_screenshot=True,
            supports_waveform=True,
        )

    hmp_model = next((model for model in ("HMP4030", "HMP4040", "HMP2020", "HMP2030") if model in compact), None)
    if hmp_model is not None:
        return DeviceProfile(
            manufacturer="Rohde & Schwarz / Hameg",
            model_family=hmp_model,
            device_type="Netzgerät",
            key="rs_hmp_power_supply",
            supports_power_supply=True,
        )

    if ("LECROY" in compact or "TELEDYNELECROY" in compact) and any(model in compact for model in ("WAVEPRO", "WAVERUNNER", "SDA", "ZI")):
        return DeviceProfile(
            manufacturer="Teledyne LeCroy",
            model_family="WavePro/WaveRunner Zi",
            device_type="Oszilloskop",
            key="lecroy_xstream",
            supports_scope_measurements=True,
            supports_waveform=True,
            supports_screenshot=True,
        )

    if "ROHDE" in compact and any(model in compact for model in ("RTB", "RTA", "RTM", "RTE", "RTO", "RTP")):
        return DeviceProfile(
            manufacturer="Rohde & Schwarz",
            model_family="RT-Series",
            device_type="Oszilloskop",
            key="rs_rt_scope",
            supports_scope_measurements=True,
            supports_screenshot=True,
            supports_waveform=True,
        )

    if "N90" in compact:
        return DeviceProfile(
            manufacturer="Keysight/Agilent",
            model_family="PXA/MXA/EXA/CXA",
            device_type="Spektrumanalysator",
            key="keysight_n90",
            supports_screenshot=True,
        )

    if "ZNB" in compact:
        return DeviceProfile(
            manufacturer="Rohde & Schwarz",
            model_family="ZNB",
            device_type="Netzwerkanalysator",
            key="rs_znb",
            supports_screenshot=True,
            supports_sparameters=True,
        )

    return UNKNOWN_PROFILE


def hmp_channel_count(model_or_idn: str) -> int:
    compact = _compact_idn(model_or_idn)
    if "HMP2020" in compact:
        return 2
    if "HMP2030" in compact or "HMP4030" in compact:
        return 3
    return 4


def _compact_idn(idn: str) -> str:
    return "".join(character for character in idn.upper() if character.isalnum())
