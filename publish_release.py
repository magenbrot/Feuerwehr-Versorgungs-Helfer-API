"""
Increments the version number in pyproject.toml and performs Git/GitHub actions.
"""

import datetime
import os
import re
import subprocess
import sys

# --- Configuration ---
FILE_PATH = "pyproject.toml"
REPO_NAME = "magenbrot/Feuerwehr-Versorgungs-Helfer-API"
MAIN_BRANCH = "main"


def get_new_version(old_version):
    """
    Calculates the new version based on YYYY.MM.PATCH logic.
    """
    current_year_month = datetime.date.today().strftime("%Y.%m")
    parts = old_version.split(".")

    if len(parts) == 3:
        old_year_month = f"{parts[0]}.{parts[1]}"
        try:
            old_patch = int(parts[2])
            if old_year_month == current_year_month:
                return f"{current_year_month}.{old_patch + 1:02d}"
        except ValueError:
            pass

    return f"{current_year_month}.00"


def run_command(command, description):
    """
    Executes a shell command using subprocess.
    """
    print(f"\n-> {description}")
    print(f"   Command: {' '.join(command)}")

    result = subprocess.run(command, check=True, capture_output=True, text=True, cwd=".")
    print("   [OK]")
    if result.stdout:
        print(f"   Stdout:\n{result.stdout.strip()}")


def update_pyproject_toml():
    """
    Reads pyproject.toml, calculates the new version, and writes it back using regex.
    """
    if not os.path.exists(FILE_PATH):
        print(f"Error: {FILE_PATH} not found.")
        sys.exit(1)

    with open(FILE_PATH, encoding="utf-8") as file:
        content = file.read()

    # Regex to find version = "..."
    version_match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not version_match:
        print("Error: Could not find version in pyproject.toml")
        sys.exit(1)

    old_version = version_match.group(1)
    new_version = get_new_version(old_version)

    print(f"Old version: {old_version} -> New version: {new_version}")

    new_content = content.replace(f'version = "{old_version}"', f'version = "{new_version}"')

    with open(FILE_PATH, "w", encoding="utf-8") as file:
        file.write(new_content)

    return new_version


def main():
    """
    Main orchestration of the version update process.
    """
    try:
        new_version = update_pyproject_toml()
        tag_name = new_version

        commands = [
            (["git", "add", FILE_PATH], f"Staging {FILE_PATH}"),
            (["git", "commit", "-m", f"Update version to {new_version}"], "Creating commit"),
            (["git", "tag", tag_name], f"Creating tag {tag_name}"),
            (["git", "push", "--atomic", "origin", MAIN_BRANCH, tag_name], "Pushing to origin"),
            (
                [
                    "gh",
                    "release",
                    "create",
                    tag_name,
                    f"--repo={REPO_NAME}",
                    f"--title=Feuerwehr-Versorgungs-Helfer-API {tag_name}",
                    "--generate-notes",
                ],
                "Creating GitHub release",
            ),
        ]

        for cmd, desc in commands:
            run_command(cmd, desc)

        print("\n" + "=" * 50 + "\nProcess finished successfully!\n" + "=" * 50)

    except subprocess.CalledProcessError as err:
        print(f"\nCommand failed: {err.stderr}")
        sys.exit(1)
    except Exception as err:  # pylint: disable=broad-except
        print(f"\nAn error occurred: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
