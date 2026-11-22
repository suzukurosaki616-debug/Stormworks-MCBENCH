-- Rolling average of one composite channel, with a couple of scalar taps.
-- Demonstrates the number/bool IO path of mccompile.
function pn(n, d) local v = property.getNumber(n) if v == 0 then return d end return v end

N = 0
sum = 0
buf = {}
function onTick()
    win = pn("Window", 30)
    x = input.getNumber(1)
    armed = input.getBool(1)

    buf[#buf + 1] = x
    sum = sum + x
    if #buf > win then
        sum = sum - buf[1]
        table.remove(buf, 1)
    end
    avg = sum / #buf

    output.setNumber(1, avg)
    output.setNumber(2, x - avg)
    output.setBool(1, armed and #buf >= win)
end
