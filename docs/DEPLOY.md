# Como publicar com segurança

O app roda no **Streamlit Cloud** e **faz deploy automático a cada `git push` na branch `main`**.
Para não deixar nenhum erro chegar ao ar, há duas camadas de proteção.

## 1. Antes de publicar — preflight local

```bash
./scripts/preflight.sh
```

Roda a checagem de sintaxe + os testes (`tests/`). Se passar, é seguro publicar:

```bash
git push origin main
```

## 2. CI no GitHub (automático)

O arquivo `.github/workflows/ci.yml` roda os **mesmos testes** a cada push e a cada
Pull Request. Para ver o resultado: **GitHub → aba _Actions_**.

- ✅ verde = a lógica principal (IQR, alinhamento de ano, "mostre a conta", escala CVM, PDF) continua funcionando.
- ❌ vermelho = algo quebrou — o GitHub manda um e-mail. **Se vier vermelho logo após publicar, avise para revertermos.**

## O que os testes cobrem (`tests/test_smoke.py`)

- Cálculo do IQR (dentro/fora do intervalo arm's length).
- **Alinhamento de ano** — pedir 2024 traz 2024 (o bug que pegamos na revisão).
- **"Mostre a conta"** — numerador/denominador corretos; rótulos markup e R$.
- **Escala da CVM** (MIL = milhares) — figuras absolutas em reais reais.
- Geração do PDF com fontes mistas (SEC + CVM + manual).

Os testes são **offline** (sem rede) — não chamam SEC/CVM, então são rápidos e estáveis.

## Fluxo mais seguro (opcional, quando quiser)

Para que o teste rode **antes** de ir ao ar (e não junto):

1. Crie uma branch: `git checkout -b minha-mudanca`
2. `git push origin minha-mudanca` e abra um **Pull Request** no GitHub.
3. Espere o CI ficar **verde** no PR.
4. **Merge** do PR → aí sim a `main` atualiza e o deploy acontece.

Hoje publicamos direto na `main` (deploy imediato); o fluxo acima é o passo seguinte
de maturidade quando o ritmo de mudanças aumentar.

## Staging (próximo nível)

Um ambiente de teste separado (um segundo app no Streamlit Cloud apontando para uma
branch `staging`) permite ver a mudança rodando antes da produção. A configuração é
feita no painel do Streamlit Cloud (fora do código) — fazer quando o produto justificar.
