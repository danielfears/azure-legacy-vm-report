"""Unit tests for v1, v2 and v3 Azure VM SKU classification."""

from __future__ import annotations

import unittest

from azure_legacy_vm_report.skus import (
    GEN_V1,
    GEN_V2,
    GEN_V3,
    classify_vm_sku,
    parent_unconstrained_sku,
)


class SkuClassificationTests(unittest.TestCase):
    def test_unversioned_v1_skus_are_classified_as_v1(self) -> None:
        cases = [
            ("Standard_B1ls", "Bv1", 1, "15/11/2028"),
            ("Standard_B2s", "Bv1", 2, "15/11/2028"),
            ("Standard_B4ms", "Bv1", 4, "15/11/2028"),
            ("Standard_B20ms", "Bv1", 20, "15/11/2028"),
            ("Standard_D1", "D", 1, "01/05/2028"),
            ("Standard_D3", "D", 4, "01/05/2028"),
            ("Standard_D14", "D", 16, "01/05/2028"),
            ("Standard_DS2", "Ds", 2, "01/05/2028"),
            ("Standard_DS13-4", "Ds", 8, "01/05/2028"),
            ("Standard_F4", "F", 4, "15/11/2028"),
            ("Standard_F8s", "Fs", 8, "15/11/2028"),
            ("Standard_G2", "G", 4, "15/11/2028"),
            ("Standard_GS5-8", "Gs", 32, "15/11/2028"),
            ("Standard_L16s", "Ls", 16, "01/05/2028"),
            ("Standard_A2", "Av1", 2, "31/08/2024"),
            ("Basic_A3", "Basic_A", 4, "31/08/2024"),
            ("ExtraSmall", "Av1", 1, "31/08/2024"),
            ("Standard_NP20s", "NP", 20, "31/05/2027"),
            ("Standard_HC44rs", "HC", 44, "31/05/2027"),
            ("Standard_HB60rs", "HB", 60, "31/08/2024"),
            ("Standard_H16mr", "H", 16, "31/08/2024"),
            ("Standard_M64ms", "M", 64, "Not announced"),
            ("Standard_NC24", "NC", 24, "30/09/2023"),
            ("Standard_DC4s", "DCs", 4, "30/06/2026"),
        ]
        for raw, series, vcpus, retire in cases:
            with self.subTest(sku=raw):
                info = classify_vm_sku(raw)
                self.assertIsNotNone(info)
                assert info is not None
                self.assertEqual(info.generation, GEN_V1)
                self.assertEqual(info.series, series)
                self.assertEqual(info.vcpus, vcpus)
                self.assertEqual(info.retirement_date, retire)

    def test_explicit_v1_v2_v3_skus(self) -> None:
        cases = [
            ("Standard_D2_v1", GEN_V1, "Dv1", 2, "15/11/2028"),
            ("Standard_DS2_v1", GEN_V1, "Dsv1", 2, "15/11/2028"),
            ("Standard_D4_v2", GEN_V2, "Dv2", 8, "01/05/2028"),
            ("Standard_DS3_v2", GEN_V2, "Dsv2", 4, "01/05/2028"),
            ("Standard_DS14-4_v2", GEN_V2, "Dsv2", 16, "01/05/2028"),
            ("Standard_F8s_v2", GEN_V2, "Fsv2", 8, "15/11/2028"),
            ("Standard_A4_v2", GEN_V2, "Av2", 4, "15/11/2028"),
            ("Standard_A8m_v2", GEN_V2, "Amv2", 8, "15/11/2028"),
            ("Standard_L16s_v2", GEN_V2, "Lsv2", 16, "15/11/2028"),
            ("Standard_B2s_v2", GEN_V2, "Bsv2", 2, "Not announced"),
            ("Standard_B4as_v2", GEN_V2, "Basv2", 4, "Not announced"),
            ("Standard_HB120rs_v2", GEN_V2, "HBv2", 120, "31/05/2027"),
            ("Standard_M192is_v2", GEN_V2, "Msv2/Mdsv2", 192, "31/03/2027"),
            ("Standard_D4_v3", GEN_V3, "Dv3", 4, "15/11/2029"),
            ("Standard_D8s_v3", GEN_V3, "Dsv3", 8, "15/11/2029"),
            ("Standard_D16-4s_v3", GEN_V3, "Dsv3", 16, "15/11/2029"),
            ("Standard_E4_v3", GEN_V3, "Ev3", 4, "15/11/2029"),
            ("Standard_E16s_v3", GEN_V3, "Esv3", 16, "15/11/2029"),
            ("Standard_E64i_v3", GEN_V3, "Ev3", 64, "15/11/2029"),
            ("Standard_E64is_v3", GEN_V3, "Esv3", 64, "15/11/2029"),
            ("Standard_DC8s_v3", GEN_V3, "DCsv3", 8, "31/10/2029"),
            ("Standard_DC16ds_v3", GEN_V3, "DCdsv3", 16, "31/10/2029"),
            ("Standard_L8s_v3", GEN_V3, "Lsv3", 8, "Not announced"),
            ("Standard_NV12s_v3", GEN_V3, "NVv3", 12, "30/09/2026"),
            ("Standard_NC4as_T4_v3", GEN_V3, "NCasT4_v3", 4, "Not announced"),
        ]
        for raw, gen, series, vcpus, retire in cases:
            with self.subTest(sku=raw):
                info = classify_vm_sku(raw)
                self.assertIsNotNone(info)
                assert info is not None
                self.assertEqual(info.generation, gen)
                self.assertEqual(info.series, series)
                self.assertEqual(info.vcpus, vcpus)
                self.assertEqual(info.retirement_date, retire)

    def test_modern_v4_v5_v6_v7_skus_return_none(self) -> None:
        for modern in (
            "Standard_D4s_v4",
            "Standard_E8as_v4",
            "Standard_D4s_v5",
            "Standard_D16ds_v5",
            "Standard_E16ds_v5",
            "Standard_D4s_v6",
            "Standard_D8ads_v6",
            "Standard_F4als_v6",
            "Standard_D4s_v7",
            "Standard_E8s_v7",
            "",
            "   ",
        ):
            with self.subTest(sku=modern):
                self.assertIsNone(classify_vm_sku(modern))

    def test_parent_unconstrained_sku(self) -> None:
        self.assertEqual(parent_unconstrained_sku("Standard_DS14-4_v2"), "Standard_DS14_v2")
        self.assertEqual(parent_unconstrained_sku("Standard_E32-8s_v3"), "Standard_E32s_v3")
        self.assertEqual(parent_unconstrained_sku("Standard_D4s_v3"), "Standard_D4s_v3")

    def test_case_normalisation_merges_mixed_case_skus(self) -> None:
        d8s = classify_vm_sku("Standard_D8S_v3")
        d2s = classify_vm_sku("Standard_D2S_v3")
        assert d8s is not None and d2s is not None
        self.assertEqual(d8s.sku, "Standard_D8s_v3")
        self.assertEqual(d2s.sku, "Standard_D2s_v3")

