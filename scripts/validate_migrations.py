import re
import json
import os
import glob
import sys

if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def test_migrations():
    migration_files = sorted(glob.glob("supabase/migrations/*.sql"))
    print(f"Encontrados {len(migration_files)} arquivos de migração:")
    for f in migration_files:
        print(f" - {f}")

    # Verificar 20260916180000_seed_tropicadelia_sectors.sql
    seed_file = "supabase/migrations/20260916180000_seed_tropicadelia_sectors.sql"
    with open(seed_file, encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(r"\(\s*'([^']+)',\s*'([^']+)',\s*'(\{.*?\})'\s*\)", re.DOTALL)
    matches = pattern.findall(content)
    print(f"\n[Validação 20260916180000_seed_tropicadelia_sectors.sql]")
    print(f"Total de setores encontrados no VALUES: {len(matches)}")

    code_regex = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,49}$")
    errors = []
    codes = set()

    for code, name, meta_str in matches:
        if code in codes:
            errors.append(f"Código duplicado: {code}")
        codes.add(code)

        if not code_regex.match(code):
            errors.append(f"Código fora do padrão: {code}")

        if not (1 <= len(name) <= 120):
            errors.append(f"Nome fora do limite (1-120): {name} ({len(name)} chars)")

        try:
            m = json.loads(meta_str)
            if not isinstance(m, dict):
                errors.append(f"Metadata não é objeto JSON: {code}")
            required_keys = ["zone", "category", "team", "priority", "coord", "cta"]
            for k in required_keys:
                if k not in m:
                    errors.append(f"Chave '{k}' faltando no metadata de {code}")
            if "coord" in m:
                coord = m["coord"]
                if not ("x" in coord and "y" in coord):
                    errors.append(f"Coordenadas inválidas em {code}: {coord}")
        except Exception as e:
            errors.append(f"Erro no JSON de {code}: {e}")

    if errors:
        print("Erros detectados:")
        for err in errors:
            print(f"  ❌ {err}")
    else:
        print(f"  ✅ Todos os {len(matches)} setores validados com sucesso!")
        print(f"  ✅ Códigos únicos e em conformidade com regex ^[A-Z0-9][A-Z0-9_-]{{0,49}}$")
        print(f"  ✅ Nomes com tamanho correto (1-120 caracteres)")
        print(f"  ✅ Metadados JSON estruturados com zone, category, team, priority, coord (x,y) e cta")

if __name__ == "__main__":
    test_migrations()
