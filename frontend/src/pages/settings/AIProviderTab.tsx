const LLM_MODEL_DEFAULTS: Record<string, string> = {
  ollama:    "llama3",
  bedrock:   "anthropic.claude-3-haiku-20240307-v1:0",
  anthropic: "claude-3-5-haiku-20241022",
  openai:    "gpt-4o-mini",
};
const EMBED_MODEL_DEFAULTS: Record<string, string> = {
  ollama:  "nomic-embed-text",
  bedrock: "amazon.titan-embed-text-v1",
  openai:  "text-embedding-3-small",
};

interface Props {
  s: Record<string, unknown>;
  selectedProvider: string;
  setSelectedProvider: (v: string) => void;
  selectedEmbedProvider: string;
  setSelectedEmbedProvider: (v: string) => void;
  llmModel: string;
  setLlmModel: (v: string) => void;
  embedModel: string;
  setEmbedModel: (v: string) => void;
  ollamaUrl: string;
  setOllamaUrl: (v: string) => void;
  bedrockRegion: string;
  setBedrockRegion: (v: string) => void;
  bedrockAccessKeyId: string;
  setBedrockAccessKeyId: (v: string) => void;
  bedrockSecretKey: string;
  setBedrockSecretKey: (v: string) => void;
  bedrockSessionToken: string;
  setBedrockSessionToken: (v: string) => void;
}

export function AIProviderTab({
  s,
  selectedProvider, setSelectedProvider,
  selectedEmbedProvider, setSelectedEmbedProvider,
  llmModel, setLlmModel,
  embedModel, setEmbedModel,
  ollamaUrl, setOllamaUrl,
  bedrockRegion, setBedrockRegion,
  bedrockAccessKeyId, setBedrockAccessKeyId,
  bedrockSecretKey, setBedrockSecretKey,
  bedrockSessionToken, setBedrockSessionToken,
}: Props) {
  const sectionHead: React.CSSProperties = {
    marginTop: "1rem", borderBottom: "1px solid var(--gray-200)", paddingBottom: "0.3rem",
  };

  return (<>
    <div className="card">
      <h3>Language Model (LLM)</h3>
      <div className="form-group">
        <label htmlFor="llm_provider">Provider</label>
        <select id="llm_provider" name="llm_provider" defaultValue={String(s.llm_provider)}
          onChange={e => {
            const p = e.target.value;
            setSelectedProvider(p);
            const stored = localStorage.getItem(`piq_llm_model_${p}`);
            setLlmModel(stored ?? LLM_MODEL_DEFAULTS[p] ?? "");
          }}>
          <option value="bedrock">Amazon Bedrock</option>
          <option value="anthropic">Anthropic</option>
          <option value="ollama">Ollama</option>
          <option value="openai">OpenAI</option>
        </select>
      </div>
      <div className="form-group">
        <label htmlFor="llm_model">Model</label>
        <input id="llm_model" name="llm_model" value={llmModel}
          onChange={e => {
            setLlmModel(e.target.value);
            localStorage.setItem(`piq_llm_model_${selectedProvider}`, e.target.value);
          }}
          placeholder={
            selectedProvider === "ollama"    ? "e.g. llama3, mistral, gemma2" :
            selectedProvider === "bedrock"   ? "e.g. anthropic.claude-3-haiku-20240307-v1:0" :
                                               "e.g. claude-3-5-haiku-20241022, gpt-4o-mini"
          } />
      </div>
      {selectedProvider === "ollama" ? (
        <div className="form-group">
          <label htmlFor="ollama_url">Ollama Server URL</label>
          <input id="ollama_url" value={ollamaUrl} onChange={e => setOllamaUrl(e.target.value)}
            placeholder="http://localhost:11434" />
          <small>The URL of your Ollama instance. No API key needed.</small>
        </div>
      ) : selectedProvider === "bedrock" ? (
        <>
          <div className="form-group">
            <label htmlFor="bedrock_region">AWS Region</label>
            <input id="bedrock_region" value={bedrockRegion} onChange={e => setBedrockRegion(e.target.value)}
              placeholder="e.g. eu-central-1, us-east-1" />
          </div>
          <div className="form-group">
            <label htmlFor="bedrock_access_key_id">Access Key ID</label>
            <input id="bedrock_access_key_id" value={bedrockAccessKeyId} onChange={e => setBedrockAccessKeyId(e.target.value)}
              placeholder="AKIA..." autoComplete="off" />
          </div>
          <div className="form-group">
            <label htmlFor="bedrock_secret_key">
              Secret Access Key
              {Boolean(s?.bedrock_has_secret) && (
                <span style={{ marginLeft: "0.5rem", fontSize: "0.75rem", color: "var(--petrol-600)", fontWeight: 500 }}>✓ stored</span>
              )}
            </label>
            <input id="bedrock_secret_key" type="password" value={bedrockSecretKey} onChange={e => setBedrockSecretKey(e.target.value)}
              placeholder={s?.bedrock_has_secret ? "••••••••••••••••••••••••  (leave blank to keep)" : "Enter secret access key"} />
          </div>
          <div className="form-group">
            <label htmlFor="bedrock_session_token">
              Session Token{" "}
              <small style={{ fontWeight: 400, color: "var(--gray-500)" }}>(optional — only for temporary STS credentials)</small>
              {Boolean(s?.bedrock_has_session_token) && (
                <span style={{ marginLeft: "0.5rem", fontSize: "0.75rem", color: "var(--petrol-600)", fontWeight: 500 }}>✓ stored</span>
              )}
            </label>
            <input id="bedrock_session_token" type="password" value={bedrockSessionToken} onChange={e => setBedrockSessionToken(e.target.value)}
              placeholder={s?.bedrock_has_session_token ? "••••••••••••••••••••••••  (leave blank to keep)" : "Leave blank for permanent IAM user keys"} />
            <small>
              Permanent IAM access keys don't need this. Required only when keys came from
              AWS SSO / <code>aws sts assume-role</code> / <code>aws sts get-session-token</code>.
              Encrypted at rest using <code>SECRET_KEY</code>.
            </small>
          </div>
        </>
      ) : (
        <div className="form-group">
          <label htmlFor="llm_credentials">API Key</label>
          <input id="llm_credentials" name="llm_credentials" type="password" defaultValue="" placeholder="Leave blank to keep current" />
          <small>Encrypted at rest. Leave empty to keep existing credentials.</small>
        </div>
      )}
      <h4 style={sectionHead}>Context</h4>
      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
        <div className="form-group" style={{ flex: 2, minWidth: "200px" }}>
          <label htmlFor="context_window_chars">Context Window (characters)</label>
          <input id="context_window_chars" name="context_window_chars" type="number" min="1000"
            defaultValue={String(s.context_window_chars ?? 128000)} />
          <small>Maximum characters of document content sent to the LLM. Default: 128,000.</small>
        </div>
        <div className="form-group" style={{ flex: 1, minWidth: "160px" }}>
          <label htmlFor="default_analysis_mode">Default Analysis Mode</label>
          <select id="default_analysis_mode" name="default_analysis_mode" defaultValue={String(s.default_analysis_mode)}>
            <option value="ocr">OCR Text</option>
            <option value="full_document">Full Document</option>
          </select>
        </div>
      </div>
    </div>

    <div className="card">
      <h3>Embeddings</h3>
      <p style={{ fontSize: "0.85rem", color: "var(--text-on-card-secondary)", marginBottom: "1rem" }}>
        Used for semantic search and smart entity selection. Can use a different provider than the LLM.
      </p>
      <div className="form-group">
        <label htmlFor="embed_provider">Embedding Provider</label>
        <select id="embed_provider" name="embed_provider" value={selectedEmbedProvider}
          onChange={e => {
            const p = e.target.value;
            setSelectedEmbedProvider(p);
            const stored = localStorage.getItem(`piq_embed_model_${p}`);
            setEmbedModel(stored ?? EMBED_MODEL_DEFAULTS[p] ?? "");
          }}>
          <option value="ollama">Ollama</option>
          <option value="bedrock">Amazon Bedrock (Titan / Cohere)</option>
          <option value="openai">OpenAI</option>
        </select>
        <small>Provider used to generate document embeddings.</small>
      </div>
      {selectedEmbedProvider === "ollama" ? (
        <>
          <p style={{ fontSize: "0.85rem", color: "var(--text-on-card-secondary)", marginBottom: "1rem", background: "var(--petrol-50)", padding: "0.75rem", borderRadius: "4px", border: "1px solid var(--petrol-200)" }}>
            Make sure the model is pulled: <code>ollama pull nomic-embed-text</code>. Embedding models are small and fast — independent of the LLM.
          </p>
          <div className="form-group">
            <label htmlFor="embedding_model">Embedding Model</label>
            <input id="embedding_model" name="embedding_model"
              value={embedModel}
              onChange={e => {
                setEmbedModel(e.target.value);
                localStorage.setItem(`piq_embed_model_${selectedEmbedProvider}`, e.target.value);
              }}
              placeholder="nomic-embed-text" />
            <small>Ollama model used for document embeddings. Must support the embed API.</small>
          </div>
          {selectedProvider !== "ollama" && (
            <div className="form-group">
              <label htmlFor="ollama_url_embed">Ollama Server URL</label>
              <input id="ollama_url_embed" value={ollamaUrl} onChange={e => setOllamaUrl(e.target.value)}
                placeholder="http://localhost:11434" />
              <small>URL of your Ollama instance for embedding generation.</small>
            </div>
          )}
        </>
      ) : selectedEmbedProvider === "bedrock" ? (
        <div className="form-group">
          <label htmlFor="embedding_model">Bedrock Embedding Model</label>
          <select id="embedding_model" name="embedding_model"
            value={embedModel || "amazon.titan-embed-text-v1"}
            onChange={e => {
              setEmbedModel(e.target.value);
              localStorage.setItem(`piq_embed_model_${selectedEmbedProvider}`, e.target.value);
            }}>
            <option value="amazon.titan-embed-text-v2:0">Titan Embed Text v2 — 1024-dim, better quality (recommended)</option>
            <option value="cohere.embed-multilingual-v3">Cohere Embed Multilingual v3 — best for non-English documents</option>
            <option value="cohere.embed-english-v3">Cohere Embed English v3 — best for English-only archives</option>
            <option value="amazon.titan-embed-text-v1">Titan Embed Text v1 — 1536-dim, legacy (keep if already indexed)</option>
          </select>
          <small>
            Uses the same AWS credentials as your Bedrock LLM.{" "}
            <strong>Changing the model requires re-indexing</strong> — use Re-index on the Processing page after saving.
          </small>
        </div>
      ) : (
        <p style={{ fontSize: "0.85rem", color: "var(--text-on-card-secondary)", background: "var(--petrol-50)", padding: "0.75rem", borderRadius: "4px", border: "1px solid var(--petrol-200)" }}>
          Embeddings are generated using OpenAI's <code>text-embedding-3-small</code> (1536-dimensional vectors).
          Uses the same API key as your OpenAI LLM.
        </p>
      )}
    </div>

    <div className="card">
      <h3>Vector Store</h3>
      <div className="form-group">
        <label htmlFor="vector_store_backend">Backend</label>
        <select id="vector_store_backend" name="vector_store_backend" defaultValue={String(s.vector_store_backend)}>
          <option value="local">Local (ChromaDB)</option>
          <option value="bedrock_kb">Amazon Bedrock Knowledge Base</option>
        </select>
      </div>
      <div className="form-group">
        <label htmlFor="bedrock_kb_id">Bedrock Knowledge Base ID</label>
        <input id="bedrock_kb_id" name="bedrock_kb_id" defaultValue={String(s.bedrock_kb_id ?? "")} placeholder="Only needed for Bedrock KB backend" />
      </div>
    </div>
  </>);
}
