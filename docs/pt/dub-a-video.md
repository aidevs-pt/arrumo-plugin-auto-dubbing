# Dobra um vídeo concluído

[English](../en/dub-a-video.md) · [Español](../es/dub-a-video.md)

Começa com uma entrega verificada, uma faixa de legendas no idioma de destino e um fornecedor e uma voz configurados. Executa estes passos a partir do repositório do Auto-Dubbing ou do pacote extraído.

## Pré-visualiza o pedido

O exemplo seleciona o espaço de trabalho 1, a execução 42 e o formato 3. Substitui os identificadores, caminhos, idioma e voz pelos teus. A pré-visualização indica as faixas disponíveis e os pedidos previstos para as legendas conhecidas. Não contacta nenhum fornecedor.

```sh
python3 tools/dub-completed-output.py /path/to/arrumo-workspaces /path/to/workspaces.sqlite 1 42 3 es elevenlabs YOUR_VOICE_ID --dry-run
```

## Renderiza e exporta

Quando o plano estiver pronto, volta a executar o comando sem a opção de pré-visualização. Usa all no lugar do identificador do formato para dobrar todas as saídas verificadas, ou adiciona formatos específicos com `--additional-format`. Se faltar uma faixa traduzida, podes importá-la no vídeo concluído ou usar um tradutor compatível.

A ferramenta anexa cada dobragem bem-sucedida à saída como MP4 alternativo. Abre o vídeo concluído para o encontrar ou exporta o ZIP da entrega. Se o lote parar devido a um erro, o relatório indica os formatos concluídos, falhados e ignorados.

Consulta [a referência do comando](../../README.md#dub-completed-outputs) para saber mais sobre tradução, revisões, cache e renderização isolada.
