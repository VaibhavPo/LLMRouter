#!/usr/bin/env python
"""
main.py — Entry point for the local AI coding assistant.

Commands:
  new <description>      - Start a new project (runs grilling)
  work <project_id>      - Work on existing project (skip grilling)
  modify <id> <change>   - Modify existing project (judge triviality, delta-grill if significant)
  list                   - List all projects
  delete <project_id>    - Delete a project's CONTEXT.md
  quit/exit              - Exit
"""

from src.orchestrator.orchestrator import Orchestrator


def cli():
    orch = Orchestrator()

    print("Local AI Coding Assistant")
    print("=" * 60)
    print("Commands:")
    print("  new <description>          - Start a new project (runs grilling)")
    print("  work <project_id>          - Work on existing project")
    print("  modify <id> <description>  - Modify existing project")
    print("  list                       - List all projects")
    print("  delete <project_id>        - Delete a project's CONTEXT.md")
    print("  test-bootstrap <path>      - Test cold bootstrap on a codebase")
    print("=" * 60)

    while True:
        cmd = input("\n> ").strip()
        if not cmd:
            continue

        parts = cmd.split(maxsplit=1)
        action = parts[0].lower()

        if action == "new":
            if len(parts) < 2:
                print("Usage: new <description>")
                continue
            description = parts[1]
            result = orch.run(description)
            print(f"\n--- CONTEXT.md Generated ---")
            if result.context_md:
                print(result.context_md)
            print(f"\n--- LLMGateway Response (if any) ---")
            if result.response:
                print(result.response)

        elif action == "work":
            if len(parts) < 2:
                print("Usage: work <project_id>")
                continue
            project_id = parts[1]
            request = input("What do you need? ").strip()
            if request:
                result = orch.run(request, project_id=project_id, skip_grilling=True)
                print(f"\n--- Response ---")
                if result.response:
                    print(result.response)

        elif action == "modify":
            if len(parts) < 2:
                print("Usage: modify <project_id> <change description>")
                continue
            
            # Parse "modify project-id change description here"
            remainder = parts[1]
            space_pos = remainder.find(" ")
            if space_pos == -1:
                print("Usage: modify <project_id> <change description>")
                continue
            
            project_id = remainder[:space_pos]
            change_request = remainder[space_pos:].strip()
            
            try:
                result = orch.modify(project_id, change_request)
                print(f"\n--- CONTEXT.md Updated ---")
                if result.was_trivial:
                    print("(Change was TRIVIAL — CONTEXT.md unchanged)")
                else:
                    print("(Change was SIGNIFICANT — CONTEXT.md updated)")
                    print(f"Sections updated: {', '.join(result.sections_updated)}")
                
                print(f"\n--- Response ---")
                if result.response:
                    print(result.response)
                    
            except ValueError as e:
                print(f"❌ {e}")
            except Exception as e:
                print(f"❌ Modify failed: {e}")

        elif action == "list":
            projects = orch.list_projects()
            if projects:
                print("\nStored projects:")
                for p in projects:
                    print(f"  - {p}")
            else:
                print("No projects yet.")

        elif action == "delete":
            if len(parts) < 2:
                print("Usage: delete <project_id>")
                continue
            project_id = parts[1]
            if orch.context_store.delete(project_id):
                print(f"Deleted {project_id}")
            else:
                print(f"Project {project_id} not found")

        elif action == "quit" or action == "exit":
            print("Goodbye.")
            break


        
        elif action == "test-bootstrap":
            """Test cold bootstrap on a codebase"""
            if len(parts) < 2:
                print("Usage: test-bootstrap <codebase_path>")
                continue
            
            codebase_path = parts[1]
            project_id = input("Project ID: ").strip()
            change_request = input("Change request: ").strip()
            
            try:
                result = orch._bootstrap_from_codebase(project_id, change_request)
                if result:
                    print(f"\n✅ Bootstrap succeeded!")
                    print(f"CONTEXT.md saved to contexts/{project_id}.md")
                else:
                    print(f"\n❌ Bootstrap failed")
            except Exception as e:
                print(f"❌ Error: {e}")
        
        else:
            print(f"Unknown command: {action}")


if __name__ == "__main__": import sys; from src.cli.main import cli; cli()