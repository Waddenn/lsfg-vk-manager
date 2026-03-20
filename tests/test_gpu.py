from __future__ import annotations

import unittest
from unittest.mock import patch

from lsfg_vk_manager.gpu import GPU_FALLBACK_NAME, detect_default_gpu


class GpuDetectionTests(unittest.TestCase):
    def test_detect_default_gpu_uses_lspci_output(self) -> None:
        lspci_output = (
            "00:00.0 Host bridge: Example Host Bridge\n"
            "04:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Phoenix3\n"
        )

        with patch("lsfg_vk_manager.gpu.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            run_mock.return_value.stdout = lspci_output

            self.assertEqual(
                detect_default_gpu(),
                "Advanced Micro Devices, Inc. [AMD/ATI] Phoenix3",
            )

    def test_detect_default_gpu_falls_back_when_unavailable(self) -> None:
        with patch("lsfg_vk_manager.gpu.subprocess.run", side_effect=OSError):
            self.assertEqual(detect_default_gpu(), GPU_FALLBACK_NAME)


if __name__ == "__main__":
    unittest.main()
