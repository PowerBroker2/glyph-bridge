import os
import subprocess
import shutil

def run_command(command):
    print(f"Running: {command}")
    subprocess.check_call(command, shell=True)

def release():
    # 1. Update packaging tools to the latest version
    print("Updating build and upload tools...")
    run_command("pip install --upgrade build twine")

    # 2. Clean previous builds
    if os.path.exists("dist"):
        print("Cleaning old build directories...")
        shutil.rmtree("dist")
    if os.path.exists("build"):
        shutil.rmtree("build")

    # 3. Build the package
    print("Building package...")
    run_command("python -m build")

    # 4. Upload to PyPI
    print("Uploading to PyPI...")
    run_command("python -m twine upload dist/*")

    print("\nRelease complete!")

if __name__ == "__main__":
    confirm = input("Have you updated the version in pyproject.toml? (y/n): ")
    if confirm.lower() == 'y':
        release()
    else:
        print("Release aborted. Please update pyproject.toml first.")