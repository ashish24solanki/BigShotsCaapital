import os
import subprocess
import shutil
from datetime import datetime

REPO_PATH = os.path.dirname(os.path.abspath(__file__))



BACKUP_PATH = r"C:\Users\ask4b\OneDrive\Backups"

def create_backup():
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    zip_name = f"backup_{timestamp}"
    output_path = os.path.join(BACKUP_PATH, zip_name)

    print("📦 Creating backup ZIP...")
    shutil.make_archive(output_path, 'zip', REPO_PATH)

    print(f"✅ Backup created: {output_path}.zip")


def run_git_command(command):
    result = subprocess.run(command, cwd=REPO_PATH, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.stderr.strip()

def has_changes():
    out, err = run_git_command("git status --porcelain")
    
    if err:
        print("❌ Git Error:", err)
        return False

    print("DEBUG STATUS:\n", out)
    return bool(out)

def ensure_gitignore():
    gitignore_path = os.path.join(REPO_PATH, ".gitignore")

    ignore_entries = [
        "access_token.txt",
        "*.log",
        "__pycache__/",
        ".env"
    ]

    if not os.path.exists(gitignore_path):
        print("📝 Creating .gitignore...")
        with open(gitignore_path, "w") as f:
            f.write("\n".join(ignore_entries) + "\n")
    else:
        with open(gitignore_path, "r") as f:
            existing = f.read()

        with open(gitignore_path, "a") as f:
            for entry in ignore_entries:
                if entry not in existing:
                    f.write(entry + "\n")

def commit_and_push(mode):
    print("🔍 Checking for changes...")

    if not has_changes():
        print("✅ No changes to commit.")
        return
    
    create_backup()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if mode == "1":
        commit_msg = f"Auto update at {timestamp}"
    elif mode == "2":
        version = datetime.now().strftime("v%Y.%m.%d-%H%M")
        commit_msg = f"Version update {version}"
    else:
        print("❌ Invalid option")
        return

    print("📦 Adding files (respecting .gitignore)...")
    run_git_command("git add .")

    print("📝 Committing...")
    out, err = run_git_command(f'git commit -m "{commit_msg}"')

    if "nothing to commit" in out.lower():
        print("⚠️ Nothing new to commit.")
        return

    print("🚀 Pushing to GitHub...")
    run_git_command("git push origin main")

    if mode == "2":
        print("🏷️ Creating version tag...")
        run_git_command(f"git tag {version}")
        run_git_command(f"git push origin {version}")

    print("✅ Done!")

if __name__ == "__main__":
    ensure_gitignore()

    print("\nChoose mode:")
    print("1 → Update only")
    print("2 → Update with version tag")

    choice = input("Enter option (1/2): ").strip()

    commit_and_push(choice)