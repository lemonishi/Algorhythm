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

function M.setup(dir)
  M.dir = dir
  local solution_win = vim.api.nvim_get_current_win()

  -- Statement on the left, roughly a third of the width.
  vim.cmd("topleft vsplit " .. vim.fn.fnameescape(dir .. "/statement.md"))
  vim.bo.buftype = "nofile"
  vim.bo.modifiable = false
  vim.bo.filetype = "markdown"
  vim.cmd("vertical resize " .. math.floor(vim.o.columns / 3))
  vim.wo.wrap = true

  vim.api.nvim_set_current_win(solution_win)

  -- Results along the bottom.
  M.results_win = open_readonly_split(dir .. "/results.txt", {
    command = "botright split",
    filetype = "text",
    height = 12,
  })
  vim.api.nvim_set_current_win(solution_win)

  vim.api.nvim_create_autocmd("BufWritePost", {
    pattern = dir .. "/solution.*",
    callback = function()
      run(
        { "algorhythm", "internal-test", dir },
        dir .. "/results.txt",
        M.results_win,
        "Running tests"
      )
    end,
  })

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
