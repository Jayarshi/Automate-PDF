from pathlib import Path

import pytest
import yaml

from local_nllb.job import load_job


def test_example_job_is_loadable() -> None:
    job = load_job("config/translation-job.yaml")
    assert job.input_file.exists()
    assert job.source_language
    assert job.target_languages
    assert job.output_directory == Path("data/output")


def test_job_requires_at_least_one_target(tmp_path) -> None:
    path = tmp_path / "job.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "input_file": "input.txt",
                "source_language": "en",
                "target_languages": [],
                "output_directory": "out",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TypeError, match="non-empty YAML list"):
        load_job(path)
