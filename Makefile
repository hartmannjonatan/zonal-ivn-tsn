.PHONY: all clean cleanall

all:
	$(MAKE) -C src all

clean:
	$(MAKE) -C src clean

cleanall:
	$(MAKE) -C src cleanall