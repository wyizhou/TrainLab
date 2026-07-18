import { useState } from 'react'
import { SysPrompt } from '../components/SysPrompt'
import { SYSTEM_PROMPT } from '../analysis/systemPrompt'
import { DEFAULT_AI_BASE_URL, useSettings, updateSettings, type UnitSystem } from './settingsStore'
import './SettingsPage.css'
import { StorageQuotaCard } from '../data-management/StorageQuotaCard'
import { useOptionalAuth } from '../auth/AuthState'

// 设置 page (contract C-14, 返工 design_rev 2). Four groups: 账户信息 / 单位制 /
// 区间设定 / AI 接口. Everything is front-end mock (G-mock) — 测试连接 probes
// nothing, 单位制 only relabels, and 区间设定 is raw-data annotation the 心率区间图
// (C-8) reads back. The rev 1 数据保留策略 group is deleted: the system offers no
// bulk-delete or expiry auto-clean of data.
//
// 单位制 / AI 接口 write straight through to the store on change; 账户信息 (needs a
// 一致性校验) and 区间设定 (needs numeric validation) commit on an explicit 保存 so a
// half-typed field never lands in the store.

export function SettingsPage() {
  const auth = useOptionalAuth()
  const settings = useSettings()

  // 账户信息 — new password ×2, validated on save.
  const [username, setUsername] = useState('audit-user')
  const [nickname, setNickname] = useState('audit-user')
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [pwError, setPwError] = useState('')
  const [pwSaved, setPwSaved] = useState(false)

  const savePassword = () => {
    setPwSaved(false)
    if (pw !== pw2) {
      setPwError('两次输入的新密码不一致')
      return
    }
    if (pw.length === 0) {
      setPwError('新密码不能为空')
      return
    }
    setPwError('')
    setPwSaved(true)
    setPw('')
    setPw2('')
  }

  // 区间设定 — edited as a draft, committed to the store on 保存 after validation.
  const { zones } = settings
  const [maxHr, setMaxHr] = useState(String(zones.maxHr))
  const [lthr, setLthr] = useState(String(zones.lthr))
  const [ftp, setFtp] = useState(String(zones.ftp))
  const [b1, setB1] = useState(String(zones.bounds[0]))
  const [b2, setB2] = useState(String(zones.bounds[1]))
  const [b3, setB3] = useState(String(zones.bounds[2]))
  const [b4, setB4] = useState(String(zones.bounds[3]))
  const [zoneError, setZoneError] = useState('')
  const [zoneSaved, setZoneSaved] = useState(false)

  const saveZones = () => {
    setZoneSaved(false)
    const nums = [maxHr, lthr, ftp, b1, b2, b3, b4].map((v) => Number(v))
    if (nums.some((n) => !Number.isFinite(n) || n <= 0)) {
      setZoneError('区间数值须为正数')
      return
    }
    const [mhr, lt, ft, u1, u2, u3, u4] = nums
    if (!(u1 < u2 && u2 < u3 && u3 < u4 && u4 < mhr)) {
      setZoneError('Z1–Z4 上界须递增且低于 MaxHR')
      return
    }
    setZoneError('')
    updateSettings((prev) => ({
      ...prev,
      zones: { maxHr: mhr, lthr: lt, ftp: ft, bounds: [u1, u2, u3, u4] },
    }))
    setZoneSaved(true)
  }

  // AI 接口 — 测试连接 is a mock probe (G-mock).
  const [aiStatus, setAiStatus] = useState('')

  const setUnit = <K extends keyof UnitSystem>(key: K, value: UnitSystem[K]) =>
    updateSettings((prev) => ({ ...prev, units: { ...prev.units, [key]: value } }))

  return (
    <section className="page settings" data-testid="page-settings" data-vc="settings-page">
      <div className="settings__head">
        <h1 data-vc="page-title">设置</h1>
      </div>

      <StorageQuotaCard demoMode={auth?.demoMode ?? true} />

      {/* 账户信息 */}
      <section className="settings__group" data-testid="settings-account" data-vc="settings-group">
        <h2 className="settings__group-title">账户信息</h2>
        <div className="settings__account-grid" data-vc="settings-account-grid">
          <div className="settings__field">
            <label className="settings__label" htmlFor="acct-username">
              用户名
            </label>
            <input
              id="acct-username"
              className="settings__input"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </div>
          <div className="settings__field">
            <label className="settings__label" htmlFor="acct-nickname">
              昵称
            </label>
            <input
              id="acct-nickname"
              className="settings__input"
              value={nickname}
              onChange={(event) => setNickname(event.target.value)}
            />
          </div>
          <div className="settings__field">
            <label className="settings__label" htmlFor="acct-pw">
              新密码
            </label>
            <input
              id="acct-pw"
              className="settings__input"
              type="password"
              placeholder="留空则不修改"
              value={pw}
              onChange={(e) => setPw(e.target.value)}
            />
          </div>
          <div className="settings__field">
            <label className="settings__label" htmlFor="acct-pw2">
              确认新密码
            </label>
            <input
              id="acct-pw2"
              className="settings__input"
              type="password"
              placeholder="再次输入"
              value={pw2}
              onChange={(e) => setPw2(e.target.value)}
            />
          </div>
        </div>
        <div className="settings__actions">
          <button type="button" className="settings__save" onClick={savePassword}>
            保存账户
          </button>
          {pwSaved && (
            <span className="settings__ok" role="status">
              密码已更新
            </span>
          )}
        </div>
        {pwError && (
          <p className="settings__error" role="alert" data-testid="settings-password-error">
            {pwError}
          </p>
        )}
      </section>

      {/* 单位制 */}
      <section className="settings__group" data-testid="settings-units" data-vc="settings-group">
        <h2 className="settings__group-title">单位制</h2>
        <div className="settings__unit-options" data-vc="settings-unit-options">
          <UnitOption
            label="距离 / 海拔"
            value={settings.units.distance}
            options={[
              ['km', '公制(km / m)'],
              ['mi', '英制(mi / ft)'],
            ]}
            onChange={(value) => setUnit('distance', value as UnitSystem['distance'])}
          />
          <UnitOption
            label="配速"
            value={settings.units.pace}
            options={[
              ['min/km', 'min/km'],
              ['min/mi', 'min/mi'],
            ]}
            onChange={(value) => setUnit('pace', value as UnitSystem['pace'])}
          />
          <UnitOption
            label="体重"
            value={settings.units.weight}
            options={[
              ['kg', 'kg'],
              ['lb', 'lb'],
            ]}
            onChange={(value) => setUnit('weight', value as UnitSystem['weight'])}
          />
        </div>
      </section>

      {/* 区间设定 */}
      <section className="settings__group" data-testid="settings-zones" data-vc="settings-group">
        <h2 className="settings__group-title settings__group-title--compact">区间设定</h2>
        <p className="settings__hint">
          仅作为原始数据的标注边界（如详情页心率区间图）；AI
          分析时随数据一并附带，系统不用它计算任何指标
        </p>
        <div className="settings__threshold-grid" data-vc="settings-threshold-grid">
          <div className="settings__field">
            <label className="settings__label" htmlFor="zone-maxhr">
              最大心率 bpm
            </label>
            <input
              id="zone-maxhr"
              className="settings__input num"
              inputMode="numeric"
              value={maxHr}
              onChange={(e) => setMaxHr(e.target.value)}
            />
          </div>
          <div className="settings__field">
            <label className="settings__label" htmlFor="zone-lthr">
              LTHR bpm
            </label>
            <input
              id="zone-lthr"
              className="settings__input num"
              inputMode="numeric"
              value={lthr}
              onChange={(e) => setLthr(e.target.value)}
            />
          </div>
          <div className="settings__field">
            <label className="settings__label" htmlFor="zone-ftp">
              FTP W
            </label>
            <input
              id="zone-ftp"
              className="settings__input num"
              inputMode="numeric"
              value={ftp}
              onChange={(e) => setFtp(e.target.value)}
            />
          </div>
        </div>
        <p className="settings__zone-label">心率区间上界 bpm（Z5 上界为最大心率）</p>
        <div className="settings__grid" data-vc="settings-zone-grid">
          <div className="settings__field">
            <label className="settings__label" htmlFor="zone-b1">
              Z1 上界
            </label>
            <input
              id="zone-b1"
              className="settings__input num"
              inputMode="numeric"
              value={b1}
              onChange={(e) => setB1(e.target.value)}
            />
          </div>
          <div className="settings__field">
            <label className="settings__label" htmlFor="zone-b2">
              Z2 上界
            </label>
            <input
              id="zone-b2"
              className="settings__input num"
              inputMode="numeric"
              value={b2}
              onChange={(e) => setB2(e.target.value)}
            />
          </div>
          <div className="settings__field">
            <label className="settings__label" htmlFor="zone-b3">
              Z3 上界
            </label>
            <input
              id="zone-b3"
              className="settings__input num"
              inputMode="numeric"
              value={b3}
              onChange={(e) => setB3(e.target.value)}
            />
          </div>
          <div className="settings__field">
            <label className="settings__label" htmlFor="zone-b4">
              Z4 上界
            </label>
            <input
              id="zone-b4"
              className="settings__input num"
              inputMode="numeric"
              value={b4}
              onChange={(e) => setB4(e.target.value)}
            />
          </div>
        </div>
        <div className="settings__actions">
          <button type="button" className="settings__save" onClick={saveZones}>
            保存区间
          </button>
          {zoneSaved && (
            <span className="settings__ok" role="status">
              区间已保存
            </span>
          )}
        </div>
        {zoneError && (
          <p className="settings__error" role="alert" data-testid="settings-zone-error">
            {zoneError}
          </p>
        )}
      </section>

      {/* AI 接口 */}
      <section className="settings__group" data-testid="settings-ai" data-vc="settings-group">
        <h2 className="settings__group-title settings__group-title--compact">
          AI 接口（OpenAI 兼容）
        </h2>
        <p className="settings__hint">参照 DeepSeek 官方接入方式：base_url + API Key + 模型名称</p>
        <div className="settings__api-form" data-vc="settings-api-form">
          <div className="settings__field">
            <label className="settings__label" htmlFor="ai-base">
              API 地址（base_url）
            </label>
            <input
              id="ai-base"
              className="settings__input"
              value={settings.ai.baseUrl}
              placeholder={DEFAULT_AI_BASE_URL}
              onChange={(e) =>
                updateSettings((prev) => ({ ...prev, ai: { ...prev.ai, baseUrl: e.target.value } }))
              }
            />
          </div>
          <div className="settings__field">
            <label className="settings__label" htmlFor="ai-key">
              API Key
            </label>
            <input
              id="ai-key"
              className="settings__input"
              type="password"
              value={settings.ai.apiKey}
              onChange={(e) =>
                updateSettings((prev) => ({ ...prev, ai: { ...prev.ai, apiKey: e.target.value } }))
              }
            />
          </div>
          <div className="settings__field">
            <label className="settings__label" htmlFor="ai-model">
              模型名称
            </label>
            <input
              id="ai-model"
              className="settings__input"
              value={settings.ai.model}
              list="model-list"
              onChange={(e) =>
                updateSettings((prev) => ({ ...prev, ai: { ...prev.ai, model: e.target.value } }))
              }
            />
            <datalist id="model-list">
              <option value="deepseek-chat" />
              <option value="deepseek-reasoner" />
            </datalist>
            <span className="settings__model-hint">
              deepseek-chat（通用）/ deepseek-reasoner（推理）；也可填其它兼容模型名
            </span>
          </div>
          <SysPrompt prompt={SYSTEM_PROMPT} />
          <div className="settings__api-actions">
            <button
              type="button"
              className="settings__save settings__save--test"
              onClick={() => setAiStatus('连接成功（模拟）')}
            >
              测试连接并识别模型
            </button>
            {aiStatus && (
              <span className="settings__ok" role="status" data-testid="settings-ai-status">
                {aiStatus}
              </span>
            )}
            <button type="button" className="settings__save">
              保存配置
            </button>
          </div>
        </div>
      </section>
    </section>
  )
}

type UnitOptionProps = {
  label: string
  value: string
  options: ReadonlyArray<readonly [string, string]>
  onChange: (value: string) => void
}

function UnitOption({ label, value, options, onChange }: UnitOptionProps) {
  return (
    <div className="settings__unit-row">
      <span className="settings__unit-label">{label}</span>
      <div className="settings__unit-chips">
        {options.map(([optionValue, optionLabel]) => (
          <button
            key={optionValue}
            type="button"
            className={
              optionValue === value
                ? 'settings__unit-chip settings__unit-chip--active'
                : 'settings__unit-chip'
            }
            aria-pressed={optionValue === value}
            onClick={() => onChange(optionValue)}
          >
            {optionLabel}
          </button>
        ))}
      </div>
    </div>
  )
}
