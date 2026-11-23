import json

from survivallab.cli import main
from survivallab.data import SyntheticCohort, fixed_fixture, write_cohort


def test_generate_and_validate_cli(tmp_path, capsys):
    assert (
        main(["generate", "--size", "10", "--seed", "42", "--output", str(tmp_path)])
        == 0
    )
    capsys.readouterr()
    assert main(["validate", str(tmp_path / "observed.csv")]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True


def test_fit_cli_returns_finite_json(tmp_path, capsys):
    rows = fixed_fixture()
    write_cohort(SyntheticCohort(rows, (), {}), tmp_path)
    assert main(["fit-csv", str(tmp_path / "observed.csv")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["rate"] == 4 / 135
    assert result["intervals"]["likelihood_ratio"]["lower"] > 0
