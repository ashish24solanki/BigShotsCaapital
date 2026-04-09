import os
import subprocess
import shutil
from datetime import datetime

# ✅ Always point to repo root (one level up from this script)
REPO_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

BACKUP_PATH = r"C:\Users\ask4b\OneDrive\Backups"


# -------------------- UTIL --------------------

def run_git_command(command):
    result = subprocess.run(
        command,
        cwd=REPO_PATH,
        shell=True,
        capture_output=True,
        text=True
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def is_git_repo():
    out, err, code = run_git_command("git rev-parse --is-inside-work-tree")
    return code == 0 and "true" in out.lower()


# -------------------- BACKUP --------------------

def create_backup():
    try:
        os.makedirs(BACKUP_PATH, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        project_name = os.path.basename(REPO_PATH)
        zip_name = f"backup_{project_name}_{timestamp}"
        output_path = os.path.join(BACKUP_PATH, zip_name)

        print("📦 Creating backup ZIP...")
        shutil.make_archive(output_path, 'zip', REPO_PATH)

        print(f"✅ Backup created: {output_path}.zip")

    except Exception as e:
        print(f"❌ Backup failed: {e}")


# -------------------- GIT STATUS --------------------

def has_changes():
    out, err, code = run_git_command("git status --porcelain")

    if code != 0:
        print("❌ Git Error:", err)
        return False

    if not out:
        return False

    print("📄 Changes detected:\n", out)
    return True


# -------------------- GITIGNORE --------------------

def ensure_gitignore():
    gitignore_path = os.path.join(REPO_PATH, ".gitignore")

    ignore_entries = [
        "access_token.txt",
        "*.log",
        "__pycache__/",
        "*.pyc",
        ".env"
    ]

    try:
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

    except Exception as e:
        print(f"❌ .gitignore error: {e}")


# -------------------- MAIN LOGIC --------------------

def commit_and_push(mode):
    print("🔍 Checking for changes...")

    if not has_changes():
        print("✅ No changes to commit.")
        return

   

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    version = None

    if mode == "1":
        commit_msg = f"Auto update at {timestamp}"

    elif mode == "2":
        version = input("🏷️ Enter version tag (e.g. v2.0-MTF): ").strip()

        if not version:
            print("❌ Version cannot be empty")
            return

        # 🔒 Prevent duplicate tag
        out, _, _ = run_git_command("git tag")
        if version in out.splitlines():
            print("❌ Tag already exists!")
            return

        # ✅ BACKUP ONLY HERE
        create_backup()

        commit_msg = f"Version update {version}"

    else:
        print("❌ Invalid option")
        return

    # -------------------- ADD --------------------
    print("📦 Adding files...")
    _, err, code = run_git_command("git add .")

    if code != 0:
        print("❌ git add failed:", err)
        return

    # -------------------- COMMIT --------------------
    print("📝 Committing...")
    out, err, code = run_git_command(f'git commit -m "{commit_msg}"')

    if "nothing to commit" in out.lower():
        print("⚠️ Nothing new to commit.")
        return

    if code != 0:
        print("❌ Commit failed:", err)
        return

    # -------------------- PUSH --------------------
    print("🚀 Pushing to GitHub...")
    _, err, code = run_git_command("git push origin main")

    if code != 0:
        print("❌ Push failed:", err)
        return

    # -------------------- TAG --------------------
    if mode == "2" and version:
        print(f"🏷️ Creating tag: {version}")

        _, err, code = run_git_command(f"git tag {version}")
        if code != 0:
            print("❌ Tag creation failed:", err)
            return

        _, err, code = run_git_command(f"git push origin {version}")
        if code != 0:
            print("❌ Tag push failed:", err)
            return

    print("✅ Done!")


# -------------------- ENTRY --------------------

if __name__ == "__main__":

    if not is_git_repo():
        print("❌ Not a git repository!")
        exit()

    ensure_gitignore()

    print("\nChoose mode:")
    print("Enter 1 → Update only")
    print("Enter 2 → Update with version tag")

    choice = input("Enter option 1 or2: ").strip()

    commit_and_push(choice)