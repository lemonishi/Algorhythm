-- Layout and hooks for one rep.
--
--   left  : statement, read-only
--   right : your solution
--   below : test results, then the review
--
-- :w      runs the tests
-- :Review asks the local model for a review
--
-- Both shell out to the algorhythm CLI, which owns all the real logic; this
-- file only moves text between buffers.

local M = {}

local function open_readonly_split(path, opts)
  vim.cmd(opts.command .. " " .. vim.fn.fnameescape(path))
  vim.bo.buftype = "nofile"
  vim.bo.swapfile = false
  vim.bo.modifiable = false
  vim.bo.filetype = opts.filetype or "markdown"
  if opts.height then vim.cmd("resize " .. opts.height) end
  if opts.width then vim.cmd("vertical resize " .. opts.width) end
  return vim.api.nvim_get_current_win()
end

local function replace_buffer(win, path)
  if not win or not vim.api.nvim_win_is_valid(win) then return end
  local buf = vim.api.nvim_win_get_buf(win)
  local lines = {}
  for line in io.lines(path) do table.insert(lines, line) end
  vim.bo[buf].modifiable = true
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
  vim.bo[buf].modifiable = false
end

local function run(cmd, output_path, win, label)
  vim.notify(label .. "...", vim.log.levels.INFO)
  vim.fn.jobstart(cmd, {
    on_exit = function()
      vim.schedule(function()
        replace_buffer(win, output_path)
        vim.notify(label .. " done", vim.log.levels.INFO)
      end)
    end,
  })
end

-- Statement and solution get equal width: reading the problem and writing
-- the answer are the two halves of a rep. Recomputed rather than set once,
-- because opening the review pane takes columns from the row and would
-- otherwise take all of them from the solution.
local function balance()
  if not (M.statement_win and vim.api.nvim_win_is_valid(M.statement_win)) then
    return
  end
  local reserved = 0
  if M.review_win and vim.api.nvim_win_is_valid(M.review_win) then
    reserved = vim.api.nvim_win_get_width(M.review_win) + 1
  end
  -- One more column for the separator between statement and solution.
  local usable = vim.o.columns - reserved - 1
  vim.api.nvim_win_set_width(M.statement_win, math.floor(usable / 2))
end

function M.setup(dir)
  M.dir = dir
  local solution_win = vim.api.nvim_get_current_win()

  vim.cmd("topleft vsplit " .. vim.fn.fnameescape(dir .. "/statement.md"))
  vim.bo.buftype = "nofile"
  vim.bo.modifiable = false
  vim.bo.filetype = "markdown"
  vim.wo.wrap = true
  M.statement_win = vim.api.nvim_get_current_win()
  balance()

  vim.api.nvim_set_current_win(solution_win)

  -- Results along the bottom.
  M.results_win = open_readonly_split(dir .. "/results.txt", {
    command = "botright split",
    filetype = "text",
    height = 12,
  })
  vim.api.nvim_set_current_win(solution_win)

  -- Bound to the buffer, not to a path pattern. A pattern has to match the
  -- name nvim gives the buffer, which is the fully resolved path — on macOS
  -- the workspace lives under `/var/...` while the buffer reports
  -- `/private/var/...`, and `:w` then silently ran nothing at all.
  vim.api.nvim_create_autocmd("BufWritePost", {
    buffer = vim.api.nvim_win_get_buf(solution_win),
    callback = function()
      run(
        { "algorhythm", "internal-test", dir },
        dir .. "/results.txt",
        M.results_win,
        "Running tests"
      )
    end,
  })

  vim.api.nvim_create_autocmd("VimResized", { callback = balance })

  vim.api.nvim_create_user_command("Review", function()
    if not (M.review_win and vim.api.nvim_win_is_valid(M.review_win)) then
      local current = vim.api.nvim_get_current_win()
      M.review_win = open_readonly_split(dir .. "/review.md", {
        command = "botright vsplit",
        filetype = "markdown",
        width = math.floor(vim.o.columns / 3),
      })
      vim.wo.wrap = true
      vim.api.nvim_set_current_win(current)
      balance()
    end
    run(
      { "algorhythm", "internal-review", dir },
      dir .. "/review.md",
      M.review_win,
      "Reviewing"
    )
  end, {})

  vim.notify("algorhythm: :w runs tests, :Review grades", vim.log.levels.INFO)
end

package.loaded["algorhythm"] = M
return M
